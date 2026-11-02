import XCTest

final class NativeAcceptanceTests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func launch(_ mode: String? = nil) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = mode.map { [$0] } ?? []
        app.launch()
        addTeardownBlock { if app.state != .notRunning { app.terminate() } }
        return app
    }

    func testApplicationEntryExposesItsStartupErrorToAccessibility() {
        // The UI-only subject deliberately has no Python/image payload. Its
        // ordinary application entry must expose the real missing-package alert.
        let app = launch()
        XCTAssertTrue(app.staticTexts["AI Station could not open"].waitForExistence(timeout: 15))
        app.buttons["OK"].click()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 10))
    }

    func testRecoveryRequiresMatchingSecureFieldsAndExplicitMFAAcknowledgement() {
        let app = launch("--native-admin-recovery")
        let submit = app.buttons["Restore and reset MFA"]
        XCTAssertTrue(submit.waitForExistence(timeout: 15))
        XCTAssertFalse(submit.isEnabled)
        XCTAssertEqual(app.secureTextFields.count, 2)
        app.textFields.firstMatch.click()
        app.textFields.firstMatch.typeText("Owner")
        let password = "synthetic UI acceptance password"
        app.secureTextFields.element(boundBy: 0).click()
        app.secureTextFields.element(boundBy: 0).typeText(password)
        XCTAssertFalse(submit.isEnabled)
        app.secureTextFields.element(boundBy: 1).click()
        app.secureTextFields.element(boundBy: 1).typeText(password)
        XCTAssertFalse(submit.isEnabled)
        app.checkBoxes["Reset MFA and suspend other restored accounts"].click()
        XCTAssertTrue(submit.isEnabled)
        // Cancel rather than emitting credentials to the test runner's stdout.
        app.buttons["Cancel"].click()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 10))
    }

    func testOrdinaryRestoreAndExceptionalRecoveryAreSeparateChoices() {
        let app = launch("--native-restore-review")
        XCTAssertTrue(app.buttons["Restore backup"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["Administrator recovery…"].exists)
        app.buttons["Cancel"].click()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 10))
    }

    func testBackupFolderPickerCanBeCanceledWithoutSelectingUserFiles() {
        let app = launch("--native-backup-folder")
        XCTAssertTrue(app.buttons["Check backup"].waitForExistence(timeout: 15))
        app.buttons["Cancel"].click()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 10))
    }
}
