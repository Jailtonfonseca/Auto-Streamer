from playwright.sync_api import sync_playwright, expect
import time

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    # Log in
    page.goto("http://localhost:8080/login")
    page.fill("input[name='password']", "admin")
    page.click("button[type='submit']")
    page.wait_for_url("http://localhost:8080/")

    # Navigate to settings page
    page.goto("http://localhost:8080/settings")
    expect(page.locator("h2")).to_contain_text("Configuration")

    # Fill out the form
    page.fill("input[name='rtmp_url']", "rtmp://new-url.com/live")
    page.fill("input[name='stream_key']", "new-stream-key")
    page.fill("input[name='openai_api_key']", "new-openai-key")
    page.fill("input[name='admin_pass_hash']", "new-hash")

    # Ensure the button is ready and click it
    save_button = page.locator("button[type='submit']")
    expect(save_button).to_be_visible()
    save_button.click()

    # Wait for the success message to appear
    success_message = page.locator("#settings-form-response")
    expect(success_message).to_contain_text("Settings updated successfully!")

    # Take a screenshot after submitting
    page.screenshot(path="jules-scratch/verification/settings_submitted.png")

    browser.close()

with sync_playwright() as playwright:
    run(playwright)
