from playwright.sync_api import sync_playwright

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    # Go to the login page
    page.goto("http://localhost:8080/login")

    # Fill in the password and click login
    page.fill("input[name='password']", "admin")
    page.click("button[type='submit']")

    # Wait for the dashboard to load and take a screenshot
    page.wait_for_url("http://localhost:8080/")
    page.screenshot(path="jules-scratch/verification/dashboard.png")

    browser.close()

with sync_playwright() as playwright:
    run(playwright)
