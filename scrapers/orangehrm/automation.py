"""
scrapers/orangehrm/automation.py
OrangeHRM Employee Data Automation (Playwright)

Logs into OrangeHRM demo portal, searches employees
by department, saves each profile as PDF + metadata JSON.

Follows exact same pattern as university offer automation:
  - ActionError on every UI step
  - PageHelper (safe_click / safe_fill / wait)
  - StatusTracker dataclass
  - Screenshots at every stage
"""

import json
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page

from config import (
    TIMEOUT_MS,
    TIMEOUT_SHORT_MS,
    ORANGEHRM_URL,
    ORANGEHRM_USERNAME,
    ORANGEHRM_PASSWORD,
    DOWNLOADS_DIR,
    SCREENSHOTS_DIR,
)
from core.pdf_handler import merge_pdfs, delete_all_pdfs
from scrapers.orangehrm.response import ORANGEHRM_RESPONSE_DEFAULT

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# ACTION ERROR
# ══════════════════════════════════════════════════════════════════════════════
class ActionError(Exception):
    def __init__(self, step: str, message: str):
        self.step    = step
        self.message = message
        super().__init__(f"[{step}] {message}")


# ══════════════════════════════════════════════════════════════════════════════
# STATUS TRACKER
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class StatusTracker:
    websiteStatus:   str = "Not processed"
    loginStatus:     str = "Not processed"
    navigationStatus: str = "Not processed"
    scrapeStatus:    str = "Not processed"
    downloadStatus:  str = "Not processed"
    employeesFound:  str = "N/A"
    employeesSaved:  str = "N/A"
    jobId:           str = "N/A"
    department:      str = "N/A"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE HELPER
# ══════════════════════════════════════════════════════════════════════════════
class PageHelper:
    def __init__(self, page: Page):
        self.page = page

    async def wait(self, ms: int = None):
        await self.page.wait_for_timeout(ms or TIMEOUT_MS)

    async def short_wait(self):
        await self.page.wait_for_timeout(TIMEOUT_SHORT_MS)

    async def wait_for_selector(
        self, selector: str, timeout: int = 15_000
    ) -> bool:
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    async def safe_click(
        self, selector: str, step: str, timeout: int = 15_000
    ) -> None:
        found = await self.wait_for_selector(selector, timeout)
        if not found:
            raise ActionError(step, f"Element not found: {selector}")
        try:
            await self.page.click(selector)
        except Exception as e:
            raise ActionError(step, f"Failed to click {selector}: {e}")

    async def safe_fill(
        self, selector: str, value: str, step: str, timeout: int = 15_000
    ) -> None:
        found = await self.wait_for_selector(selector, timeout)
        if not found:
            raise ActionError(step, f"Element not found: {selector}")
        try:
            await self.page.fill(selector, value)
        except Exception as e:
            raise ActionError(step, f"Failed to fill {selector}: {e}")

    async def is_visible(self, selector: str) -> bool:
        try:
            return await self.page.is_visible(selector)
        except Exception:
            return False

    async def is_existing(self, selector: str) -> bool:
        try:
            return await self.page.locator(selector).count() > 0
        except Exception:
            return False

    async def scroll_to_bottom(self):
        await self.page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# ORANGEHRM SERVICE
# ══════════════════════════════════════════════════════════════════════════════
class OrangeHRMService:
    """
    Logs into OrangeHRM demo portal.
    Navigates to PIM → Employee List.
    Searches by department.
    Saves each employee profile as PDF + metadata JSON.
    """

    def __init__(self):
        self._page:            Optional[Page]          = None
        self._ph:              Optional[PageHelper]    = None
        self._status:          Optional[StatusTracker] = None
        self._dto:             Optional[dict]          = None
        self._job_id:          Optional[str]           = None
        self._department:      Optional[str]           = None
        self._max_employees:   int                     = 10
        self._download_path:   Optional[Path]          = None
        self._screenshot_path: Optional[Path]          = None
        self._all_employees:   list                    = []

    # ── ENTRY POINT ───────────────────────────────────────────────────────────
    async def run(self, dto: dict):
        """
        Entry point.
        dto = {
            "job_id":        "001",
            "department":    "IT",
            "max_employees": 10
        }
        """
        self._dto           = dto
        self._job_id        = str(dto.get("job_id", "unknown"))
        self._department    = dto.get("department", {})
        self._max_employees = int(dto.get("max_employees", 10))
        self._status        = StatusTracker(
            jobId=self._job_id,
            department=self._department.get("jobTitle", "") or "All",
        )

        # setup local directories
        self._download_path = (
            Path(DOWNLOADS_DIR) / "orangehrm" / self._job_id
        )
        self._screenshot_path = (
            Path(SCREENSHOTS_DIR) / "orangehrm" / self._job_id
        )
        self._download_path.mkdir(parents=True, exist_ok=True)
        self._screenshot_path.mkdir(parents=True, exist_ok=True)

        pw_instance   = None
        browser       = None
        error_message = None

        try:
            pw_instance = await async_playwright().start()
            browser     = await pw_instance.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--start-maximized",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
            )
            self._page = await context.new_page()
            self._ph   = PageHelper(self._page)

            # ── Step 1: Open portal ───────────────────────────────────────────
            try:
                await self._open_portal()
                self._status.websiteStatus = "Success"
                logger.info("[OrangeHRM] Portal opened")
            except ActionError as ae:
                self._status.websiteStatus = "Failed"
                error_message = ae.message
                raise

            # ── Step 2: Login ─────────────────────────────────────────────────
            try:
                await self._login()
                self._status.loginStatus = "Success"
                logger.info("[OrangeHRM] Login success")
            except ActionError as ae:
                self._status.loginStatus = "Failed"
                error_message = ae.message
                raise

            # ── Step 3: Navigate to Employee List ─────────────────────────────
            try:
                await self._navigate_to_employee_list()
                self._status.navigationStatus = "Success"
                logger.info("[OrangeHRM] Navigation success")
            except ActionError as ae:
                self._status.navigationStatus = "Failed"
                error_message = ae.message
                raise

            # ── Step 4: Search employees ──────────────────────────────────────
            try:
                await self._search_employees()
            except ActionError as ae:
                self._status.scrapeStatus = "Failed"
                error_message = ae.message
                raise

            # ── Step 5: Process each employee ─────────────────────────────────
            try:
                await self._process_employees()
            except ActionError as ae:
                self._status.scrapeStatus = "Failed"
                error_message = ae.message
                raise

        except ActionError as ae:
            error_message = ae.message
            logger.error(
                "[OrangeHRM] ActionError [%s]: %s", ae.step, ae.message
            )
            for key, val in self._status.to_dict().items():
                if val == "Not processed":
                    setattr(self._status, key, "Failed")

        except Exception as e:
            error_message = str(e)
            logger.error("[OrangeHRM] Fatal error: %s", e)
            traceback.print_exc()
            for key, val in self._status.to_dict().items():
                if val == "Not processed":
                    setattr(self._status, key, "Failed")

        finally:
            # merge all screenshots into one PDF
            try:
                merge_pdfs(
                    self._screenshot_path,
                    f"report-{self._job_id}.pdf"
                )
            except Exception as e:
                logger.error("[OrangeHRM] PDF merge error: %s", e)

            # if browser:
            #     try:
            #         await browser.close()
            #     except Exception:
            #         pass
            # if pw_instance:
            #     try:
            #         await pw_instance.stop()
            #     except Exception:
            #         pass

        logger.info(
            "[OrangeHRM] Final status: %s", self._status.to_dict()
        )
        return {
            "scraper":  "orangehrm",
            "success":  self._status.scrapeStatus == "Success",
            "status":   self._status.to_dict(),
            "error":    error_message,
        }

    # ── STEP 1: Open portal ───────────────────────────────────────────────────
    async def _open_portal(self):
        STEP = "openPortal"
        try:
            await self._page.goto(
                f"{ORANGEHRM_URL}/web/index.php/auth/login",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
        except Exception as e:
            raise ActionError(STEP, f"Portal not accessible: {e}")

    # ── STEP 2: Login ─────────────────────────────────────────────────────────
    async def _login(self):
        STEP = "login"
        await self._ph.wait()

        # fill username
        await self._ph.safe_fill(
            "input[name='username']",
            ORANGEHRM_USERNAME,
            STEP
        )

        # fill password
        await self._ph.safe_fill(
            "input[name='password']",
            ORANGEHRM_PASSWORD,
            STEP
        )

        # click login
        await self._ph.safe_click(
            "button[type='submit']",
            STEP
        )

        await self._ph.wait()

        # check for login error
        error_exists = await self._ph.is_existing(
            "//p[contains(@class,'oxd-alert-content-text')]"
        )
        if error_exists:
            error_text = await self._page.text_content(
                "//p[contains(@class,'oxd-alert-content-text')]"
            )
            raise ActionError(STEP, f"Login failed: {error_text}")

        # confirm dashboard loaded
        dashboard = await self._ph.wait_for_selector(
            "//h6[text()='Dashboard']", timeout=10_000
        )
        if not dashboard:
            raise ActionError(STEP, "Dashboard not loaded after login")

        await self._take_screenshot("1-login-success.pdf")

    # ── STEP 3: Navigate to Employee List ─────────────────────────────────────
    async def _navigate_to_employee_list(self):
        STEP = "navigateToEmployeeList"
        await self._ph.wait()
        await self._ph.wait()

        try:
            pim_tab = self._page.locator(
                    "//a[span[contains(normalize-space(), 'PIM')]]"
            )
            await pim_tab.click()
        except Exception as e:
            raise ActionError(STEP, f"Navigation failed: {e}")

        await self._ph.wait()
        await self._ph.wait()

        # confirm page loaded
        loaded = await self._ph.wait_for_selector(
            "//h5[text()='Employee Information']",
            timeout=10_000
        )
        if not loaded:
            raise ActionError(STEP, "Employee List page not loaded")

        await self._take_screenshot("2-employee-list.pdf")
        logger.info("[OrangeHRM] Employee list page loaded")

    # ── STEP 4: Search employees ──────────────────────────────────────────────
    async def _search_employees(self):
        STEP = "searchEmployees"
        await self._ph.wait()

        if self._job_id and self._job_id != "":
            # ── Search by Employee ID ─────────────────────────────────
            try:
                employee_id_input = self._page.locator(
                    "//label[text()='Employee Id']"
                    "/ancestor::div[contains(@class,'oxd-input-group')]"
                    "//input"
                )
                await employee_id_input.fill(self._job_id)
                logger.info(
                    "[OrangeHRM] Searching by Employee ID: %s",
                    self._job_id
                )
            except Exception as e:
                logger.warning(
                    "[OrangeHRM] Employee ID fill failed: %s", e
                )
        else:
            # ── Search by department filters ──────────────────────────
            dept = self._department if isinstance(
                self._department, dict
            ) else {}

            job_title    = dept.get("jobTitle", "")
            emp_status   = dept.get("empStatus", "")
            sub_unit     = dept.get("subUnit", "")

            if job_title:
                await self._select_dropdown(
                    "//label[text()='Job Title']"
                    "/ancestor::div[contains(@class,'oxd-input-group')]"
                    "//div[contains(@class,'oxd-select-text')]",
                    job_title, "jobTitle"
                )
            elif emp_status:
                await self._select_dropdown(
                    "//label[text()='Employment Status']"
                    "/ancestor::div[contains(@class,'oxd-input-group')]"
                    "//div[contains(@class,'oxd-select-text')]",
                    emp_status, "empStatus"
                )
            elif sub_unit:
                await self._select_dropdown(
                    "//label[text()='Sub Unit']"
                    "/ancestor::div[contains(@class,'oxd-input-group')]"
                    "//div[contains(@class,'oxd-select-text')]",
                    sub_unit, "subUnit"
                )
            else:
                logger.info(
                    "[OrangeHRM] No filters — fetching all employees "
                    "up to max: %d", self._max_employees
                )

        await self._ph.wait()

        # click Search
        await self._ph.safe_click(
            "//button[@type='submit'][normalize-space()='Search']",
            STEP
        )
        await self._ph.wait()
        await self._ph.wait()
        await self._take_screenshot("3-search-results.pdf")

        # get result count
        count_exists = await self._ph.is_existing(
            "//span[contains(@class,'oxd-text--span')"
            " and contains(text(),'Record')]"
        )
        if count_exists:
            count_text = await self._page.text_content(
                "//span[contains(@class,'oxd-text--span')"
                " and contains(text(),'Record')]"
            )
            logger.info("[OrangeHRM] Result: %s", count_text)
            self._status.employeesFound = count_text.strip()

    # ── STEP 5: Process employees ─────────────────────────────────────────────
    async def _process_employees(self):
        STEP = "processEmployees"

        # ── wait for table to fully load ──────────────────────────────
        await self._ph.wait_for_selector(
            "//div[@class='oxd-table-body']//div[@role='row']",
            timeout=15_000
        )

        # ── Extract all employee data at once using JavaScript ────────
        all_rows_data = await self._page.evaluate("""
            () => {
                const rows = Array.from(document.querySelectorAll('div.oxd-table-body div[role="row"]'));
                return rows.map((row, idx) => {
                    const cells = Array.from(row.querySelectorAll('div[role="cell"]'));
                    return {
                        index: idx,
                        cells: cells.map(cell => (cell.innerText || '').trim())
                    };
                });
            }
        """)

        logger.info("[OrangeHRM] Found %d rows in table", len(all_rows_data))

        employees_saved = 0

        # ── Generic cover page (only when no job_id) ──────────────────
        if not self._job_id or self._job_id == "":
            # use base path for cover page
            base_screenshot_path = (
                Path(SCREENSHOTS_DIR) / "orangehrm" / "general"
            )
            base_screenshot_path.mkdir(parents=True, exist_ok=True)

            # temporarily set screenshot path to general folder
            original_screenshot_path = self._screenshot_path
            self._screenshot_path = base_screenshot_path
            await self._generate_generic_cover_page()
            # restore
            self._screenshot_path = original_screenshot_path

        for row_data in all_rows_data[:self._max_employees]:
            i = row_data["index"]
            cells = row_data["cells"]
            logger.info("[OrangeHRM] Checked %d rows", i)
            try:
                # ── Step 1: extract basic data from cells ─────────────
                employee_data = await self._extract_employee_data_from_cells(cells, i)
                logger.info("[OrangeHRM] Checked employee data: %s", employee_data)

                if not employee_data:
                    continue

                # ── Step 2: get emp_id from table ─────────────────────
                emp_id = employee_data.get("emp_id", "")
                if not emp_id:
                    logger.warning(
                        "[OrangeHRM] No emp_id for row %d — skipping", i
                    )
                    continue

                # ── Step 3: NOW create per-employee folders ───────────
                # each employee gets their own folder named by emp_id
                self._download_path = (
                    Path(DOWNLOADS_DIR)
                    / "orangehrm"
                    / emp_id              # ← folder named by emp_id
                )
                self._screenshot_path = (
                    Path(SCREENSHOTS_DIR)
                    / "orangehrm"
                    / emp_id              # ← folder named by emp_id
                )
                self._download_path.mkdir(parents=True, exist_ok=True)
                self._screenshot_path.mkdir(parents=True, exist_ok=True)

                logger.info(
                    "[OrangeHRM] Created folder for emp_id: %s", emp_id
                )

                # ── Step 4: copy cover page into employee folder ──────
                if not self._job_id or self._job_id == "":
                    await self._copy_cover_page_to_employee_folder(
                        emp_id
                    )

                # ── Step 5: take row screenshot AFTER folder created ──
                await self._take_screenshot(
                    f"1-{emp_id}-row.pdf"
                )

                # ── Step 6: check required fields ────────────────────
                missing = self._check_missing_fields(employee_data)

                if missing:
                    logger.info(
                        "[OrangeHRM] Employee %s missing: %s — editing",
                        employee_data.get("name"), missing
                    )
                    await self._click_edit_and_screenshot(
                        employee_data, i
                    )
                else:
                    logger.info(
                        "[OrangeHRM] Employee %s complete — saving profile",
                        employee_data.get("name")
                    )
                    await self._save_employee_profile(employee_data, i)

                # ── Step 7: generate voucher PDF ──────────────────────
                await self._generate_voucher_pdf(employee_data, i)

                # ── Step 8: merge all screenshots for this employee ───
                merge_pdfs(
                    self._screenshot_path,
                    f"report-{emp_id}.pdf"
                )

                self._all_employees.append(employee_data)
                employees_saved += 1

                logger.info(
                    "[OrangeHRM] ✓ Saved employee %d: %s — folder: %s",
                    i + 1, employee_data.get("name"), emp_id
                )

                # ── Step 9: go back to list ───────────────────────────
                await self._page.goto(
                    f"{ORANGEHRM_URL}/web/index.php/pim/viewEmployeeList",
                    wait_until="domcontentloaded",
                    timeout=20_000,
                )
                await self._ph.wait()

                # re-search to restore results
                await self._ph.safe_click(
                    "//button[@type='submit'][normalize-space()='Search']",
                    STEP
                )
                await self._ph.wait()
                await self._ph.wait()

            except Exception as e:
                logger.error(
                    "[OrangeHRM] Error employee %d: %s", i, e
                )
                continue

        self._status.employeesSaved = str(employees_saved)
        self._status.scrapeStatus   = "Success"
        self._status.downloadStatus = "Success"
        logger.info(
            "[OrangeHRM] Complete — saved %d employees", employees_saved
        )
    
    # ── EXTRACT EMPLOYEE DATA FROM CELLS ────────────────────────────────────────
    async def _extract_employee_data_from_cells(
        self, cells: list, index: int
    ) -> Optional[dict]:
        logger.info(
            "[OrangeHRM] Extracting employee data from cells. Index=%s",
            index
        )
        try:
            logger.info(
                "[OrangeHRM] Row %d — cells found: %d", index, len(cells)
            )

            if len(cells) < 4:
                logger.warning(
                    "[OrangeHRM] Row %d — not enough cells (%d), skipping",
                    index, len(cells)
                )
                return None

            # Extract text from each cell (index 0 is checkbox, data starts at 1)
            emp_id     = (cells[1] or "").strip()
            first_name = (cells[2] or "").strip()
            last_name  = (cells[3] or "").strip()
            full_name  = f"{first_name} {last_name}".strip()

            job_title = (cells[4] or "").strip() if len(cells) > 4 else ""
            emp_status = (cells[5] or "").strip() if len(cells) > 5 else ""
            sub_unit = (cells[6] or "").strip() if len(cells) > 6 else ""
            supervisor = (cells[7] or "").strip() if len(cells) > 7 else ""

            logger.info(
                "[OrangeHRM] Row %d — emp_id: %s name: %s job: %s",
                index, emp_id, full_name, job_title
            )

            # skip if no emp_id extracted
            if not emp_id:
                logger.warning(
                    "[OrangeHRM] Row %d — empty emp_id, skipping", index
                )
                return None

            profile_url = (
                f"{ORANGEHRM_URL}/web/index.php"
                f"/pim/viewPersonalDetails/empNumber/{emp_id}"
            )

            return {
                "index":       index + 1,
                "emp_id":      emp_id,
                "name":        full_name,
                "first_name":  first_name,
                "last_name":   last_name,
                "job_title":   job_title,
                "status":      emp_status,
                "sub_unit":    sub_unit,
                "supervisor":  supervisor,
                "profile_url": profile_url,
                "department":  self._department or "All",
                "job_id":      self._job_id,
            }

        except Exception as e:
            logger.error(
                "[OrangeHRM] Extract error row %d: %s", index, e
            )
            return None

    # ── SAVE EMPLOYEE PROFILE AS PDF ─────────────────────────────────────────
    async def _save_employee_profile(
        self, employee_data: dict, index: int
    ):
        STEP = "saveEmployeeProfile"
        try:
            profile_url = employee_data.get("profile_url", "")
            if not profile_url:
                return

            # navigate to profile page
            await self._page.goto(
                profile_url,
                wait_until="domcontentloaded",
                timeout=20_000,
            )
            await self._ph.wait()

            # safe name for filename
            safe_name = "".join(
                c for c in employee_data.get("name", f"employee-{index}")
                if c.isalnum() or c in (" ", "-", "_")
            ).strip().replace(" ", "-")[:50]

            # save as PDF
            pdf_path = (
                self._download_path
                / f"{index + 1}-{safe_name}.pdf"
            )
            await self._page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
            )

            # also take screenshot for report
            await self._take_screenshot(
                f"{index + 1}-{safe_name}-screenshot.pdf"
            )

            logger.info("[OrangeHRM] Profile PDF saved: %s", pdf_path)

        except Exception as e:
            logger.error(
                "[OrangeHRM] Profile save error %d: %s", index, e
            )

    # ── HELPER ────────────────────────────────────────────────────────────
    def _check_missing_fields(self, employee_data: dict) -> list:
        """
        Check if required fields are present.
        Returns list of missing field names.
        """
        required = {
            "job_title":  "Job Title",
            "status":     "Employment Status",
            "sub_unit":   "Sub Unit",
            "supervisor": "Supervisor",
        }
        missing = []
        for key, label in required.items():
            val = employee_data.get(key, "").strip()
            if not val:
                missing.append(label)
        return missing

    async def _click_edit_and_screenshot(
        self, employee_data: dict, index: int
    ):
        """
        Navigate to employee profile page →
        take screenshot → extract additional data if needed.
        """
        STEP = "clickEditAndScreenshot"
        try:
            emp_id = employee_data.get("emp_id", "")

            # navigate directly to profile page
            profile_url = employee_data.get("profile_url", "")
            await self._page.goto(
                profile_url,
                wait_until="domcontentloaded",
                timeout=20_000,
            )
            await self._ph.wait()

            # screenshot of profile page
            await self._take_screenshot(
                f"{index + 1}-{emp_id}-profile-page.pdf"
            )

            logger.info(
                "[OrangeHRM] Profile screenshot taken for: %s",
                employee_data.get("name")
            )

        except Exception as e:
            logger.error(
                "[OrangeHRM] Edit screenshot error %d: %s", index, e
            )

    async def _select_dropdown(
        self, dropdown_selector: str,
        value: str, field_name: str
    ):
        """Reusable dropdown selector."""
        try:
            dropdown = self._page.locator(dropdown_selector)
            await dropdown.click()
            await self._ph.short_wait()

            option = self._page.locator(
                f"//div[@role='option']//span[text()='{value}']"
            )
            if await option.count() > 0:
                await option.click()
                logger.info(
                    "[OrangeHRM] %s selected: %s", field_name, value
                )
            else:
                logger.warning(
                    "[OrangeHRM] %s option '%s' not found",
                    field_name, value
                )
        except Exception as e:
            logger.warning(
                "[OrangeHRM] Dropdown '%s' failed: %s", field_name, e
            )
    
    
    # ── FOR SPECIFIC EMPLOYEE ID ─────────────────────────────────────────────────
    async def _generate_voucher_pdf(
        self, employee_data: dict, index: int
    ):
        """
        Generate voucher confirmation PDF per employee.
        Statement confirms employee is eligible for Amazon voucher
        based on their report details.
        """
        try:
            name       = employee_data.get("name", "N/A")
            emp_id     = employee_data.get("emp_id", "N/A")
            job_title  = employee_data.get("job_title") or "Not specified"
            status     = employee_data.get("status") or "Not specified"
            sub_unit   = employee_data.get("sub_unit") or "Not specified"
            supervisor = employee_data.get("supervisor") or "Not specified"
            dept       = employee_data.get("department") or "Not specified"

            # determine eligibility
            missing = self._check_missing_fields(employee_data)
            is_eligible = len(missing) == 0

            eligibility_text = (
                "ELIGIBLE ✓" if is_eligible
                else f"NOT ELIGIBLE ✗ — Missing: {', '.join(missing)}"
            )
            eligibility_color = "#2e7d32" if is_eligible else "#c62828"

            voucher_html = f"""
            <html>
            <body style="font-family: Arial; padding: 40px;
                        max-width: 700px; margin: auto;">

                <div style="text-align: center; margin-bottom: 30px;">
                    <h1 style="color: #1a237e;">
                        Employee Performance Voucher
                    </h1>
                    <p style="color: #666;">
                        OrangeHRM Automation System
                    </p>
                </div>

                <hr style="border: 2px solid #1a237e;"/>

                <div style="margin: 30px 0;">
                    <h2 style="color: #333;">Employee Details</h2>
                    <table style="width:100%; border-collapse: collapse;
                                font-size: 15px;">
                        <tr style="background: #f5f5f5;">
                            <td style="padding: 10px; font-weight: bold;
                                    width: 40%;">Employee ID</td>
                            <td style="padding: 10px;">{emp_id}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px;
                                    font-weight: bold;">Full Name</td>
                            <td style="padding: 10px;">{name}</td>
                        </tr>
                        <tr style="background: #f5f5f5;">
                            <td style="padding: 10px;
                                    font-weight: bold;">Job Title</td>
                            <td style="padding: 10px;">{job_title}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px;
                                    font-weight: bold;">
                                    Employment Status</td>
                            <td style="padding: 10px;">{status}</td>
                        </tr>
                        <tr style="background: #f5f5f5;">
                            <td style="padding: 10px;
                                    font-weight: bold;">Sub Unit</td>
                            <td style="padding: 10px;">{sub_unit}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px;
                                    font-weight: bold;">Supervisor</td>
                            <td style="padding: 10px;">{supervisor}</td>
                        </tr>
                        <tr style="background: #f5f5f5;">
                            <td style="padding: 10px;
                                    font-weight: bold;">Department</td>
                            <td style="padding: 10px;">{dept}</td>
                        </tr>
                    </table>
                </div>

                <hr style="border: 1px solid #ccc;"/>

                <div style="margin: 30px 0; padding: 20px;
                            border: 2px solid {eligibility_color};
                            border-radius: 8px;">
                    <h2 style="color: {eligibility_color};">
                        Voucher Status: {eligibility_text}
                    </h2>
                    <p style="font-size: 15px; line-height: 1.8;">
                        This is to confirm that employee
                        <strong>{name}</strong> (ID: {emp_id}),
                        working as <strong>{job_title}</strong>
                        under the supervision of
                        <strong>{supervisor}</strong>
                        in the <strong>{sub_unit}</strong>
                        sub-unit of the
                        <strong>{dept}</strong> department,
                        {"<strong>is eligible</strong> to receive an "
                        "<strong>Amazon Voucher</strong> based on their "
                        "performance report, as all required profile "
                        "details are complete and verified."
                        if is_eligible else
                        "is <strong>currently not eligible</strong> "
                        "for the Amazon Voucher as the following "
                        "required profile details are incomplete: "
                        f"<strong>{', '.join(missing)}</strong>. "
                        "Please update the profile to become eligible."}
                    </p>
                </div>

                <hr style="border: 1px solid #ccc;"/>

                <div style="margin-top: 40px; display: flex;
                            justify-content: space-between;">
                    <div style="text-align: center;">
                        <div style="border-top: 1px solid #333;
                                    width: 200px; margin: auto;">
                        </div>
                        <p>Supervisor Signature</p>
                        <p style="color: #666;">{supervisor}</p>
                    </div>
                    <div style="text-align: center;">
                        <div style="border-top: 1px solid #333;
                                    width: 200px; margin: auto;">
                        </div>
                        <p>HR Signature</p>
                        <p style="color: #666;">Human Resources</p>
                    </div>
                </div>

                <p style="text-align: center; color: #999;
                        font-size: 12px; margin-top: 40px;">
                    Generated by OrangeHRM Automation System •
                    {__import__('datetime').datetime.now()
                    .strftime('%d %B %Y %H:%M')}
                </p>

            </body>
            </html>
            """

            # save voucher HTML as PDF
            safe_name = "".join(
                c for c in name
                if c.isalnum() or c in (" ", "-", "_")
            ).strip().replace(" ", "-")[:30]

            voucher_path = (
                self._download_path
                / f"{index + 1}-{safe_name}-voucher.pdf"
            )

            await self._page.set_content(voucher_html)
            await self._ph.wait(2000)
            await self._page.pdf(
                path=str(voucher_path),
                format="A4",
                print_background=True,
            )

            logger.info(
                "[OrangeHRM] Voucher PDF saved: %s", voucher_path
            )

        except Exception as e:
            logger.error("[OrangeHRM] Voucher PDF error: %s", e)

    # ── FOR NO SPECIFIC EMPLOYEE ID ─────────────────────────────────────────────────
    async def _generate_generic_cover_page(self):
        """
        Generate a cover page when no specific employee ID given.
        Saved as first PDF in screenshot folder.
        """
        try:
            cover_html = f"""
            <html>
            <body style="font-family: Arial; padding: 40px;">
                <h1 style="color: #333;">Employee Report</h1>
                <hr/>
                <p><strong>Generated:</strong>
                {__import__('datetime').datetime.now()
                .strftime('%d %B %Y %H:%M')}</p>
                <p><strong>Filter Applied:</strong>
                {self._department or 'All Employees'}</p>
                <p><strong>Max Records to search:</strong>
                {self._max_employees}</p>
                <p><strong>Job ID:</strong> {self._job_id or 'N/A'}</p>
                <hr/>
                <p style="color: #666; font-size: 14px;">
                    This report contains employee profile information
                    extracted from OrangeHRM. Each profile has been
                    reviewed for completeness.
                </p>
            </body>
            </html>
            """
            # write temp HTML and convert to PDF
            cover_path = self._screenshot_path / "0-cover-page.pdf"
            await self._page.set_content(cover_html)
            await self._page.pdf(
                path=str(cover_path),
                format="A4",
                print_background=True,
            )
            logger.info("[OrangeHRM] Cover page generated")

        except Exception as e:
            logger.error("[OrangeHRM] Cover page error: %s", e)


    async def _copy_cover_page_to_employee_folder(self, emp_id: str):
        """
        Copy the generic cover page into each employee's
        screenshot folder so it appears first in their merged PDF.
        """
        try:
            import shutil
            cover_source = (
                Path(SCREENSHOTS_DIR)
                / "orangehrm"
                / "general"
                / "0-cover-page.pdf"
            )
            if cover_source.exists():
                cover_dest = self._screenshot_path / "0-cover-page.pdf"
                shutil.copy2(cover_source, cover_dest)
                logger.info(
                    "[OrangeHRM] Cover page copied to: %s", emp_id
                )
        except Exception as e:
            logger.error("[OrangeHRM] Cover copy error: %s", e)

    # ── SCREENSHOT ────────────────────────────────────────────────────────────
    async def _take_screenshot(self, filename: str) -> Optional[Path]:
        if not self._screenshot_path:
            return None
        try:
            dest = self._screenshot_path / filename
            await self._page.pdf(
                path=str(dest),
                format="A4",
                print_background=True,
            )
            return dest
        except Exception as e:
            logger.error("[OrangeHRM] Screenshot error: %s", e)
            return None

    # ── FILLER ────────────────────────────────────────────────────────────   
    async def _fill(self, locator, value: str):
        """Fill a locator element directly."""
        try:
            await locator.fill(value)
        except Exception as e:
            logger.error("[OrangeHRM] Fill error: %s", e)