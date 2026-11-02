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
        let dialog = app.dialogs.firstMatch
        XCTAssertTrue(dialog.staticTexts["AI Station could not open"].waitForExistence(timeout: 15))
        dialog.buttons["OK"].click()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 10))
    }

    func testRecoveryRequiresMatchingSecureFieldsAndExplicitMFAAcknowledgement() {
        let app = launch("--native-admin-recovery")
        let dialog = app.dialogs.firstMatch
        let submit = dialog.buttons["Restore and reset MFA"]
        XCTAssertTrue(submit.waitForExistence(timeout: 15))
        XCTAssertFalse(submit.isEnabled)
        XCTAssertEqual(dialog.secureTextFields.count, 2)
        dialog.textFields.firstMatch.click()
        dialog.textFields.firstMatch.typeText("Owner")
        let password = "synthetic UI acceptance password"
        dialog.secureTextFields.element(boundBy: 0).click()
        dialog.secureTextFields.element(boundBy: 0).typeText(password)
        XCTAssertFalse(submit.isEnabled)
        dialog.secureTextFields.element(boundBy: 1).click()
        dialog.secureTextFields.element(boundBy: 1).typeText(password)
        XCTAssertFalse(submit.isEnabled)
        dialog.checkBoxes["Reset MFA and suspend other restored accounts"].click()
        XCTAssertTrue(submit.isEnabled)
        // Cancel rather than emitting credentials to the test runner's stdout.
        dialog.buttons["Cancel"].click()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 10))
    }

    func testOrdinaryRestoreAndExceptionalRecoveryAreSeparateChoices() {
        let app = launch("--native-restore-review")
        let dialog = app.dialogs.firstMatch
        XCTAssertTrue(dialog.buttons["Restore backup"].waitForExistence(timeout: 15))
        XCTAssertTrue(dialog.buttons["Administrator recovery…"].exists)
        dialog.buttons["Cancel"].click()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 10))
    }

    func testBackupFolderPickerCanBeCanceledWithoutSelectingUserFiles() {
        let app = launch("--native-backup-folder")
        let dialog = app.dialogs["open-panel"]
        XCTAssertTrue(dialog.buttons["Check backup"].waitForExistence(timeout: 15))
        dialog.buttons["Cancel"].click()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 10))
    }
}
