import AppKit
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

    func testNestedPresentationHelperCanBeControlledWithoutLaunchingAnotherInstance() throws {
        // XCTest's runner is sandboxed. The ordinary host QA driver starts the
        // exact helper; this test only attaches to and operates its actual UI.
        let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let root = repository.appendingPathComponent(".native-mac/ui-acceptance")
        let data = try Data(contentsOf: root.appendingPathComponent("helper-process.json"))
        let value = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let number = try XCTUnwrap(value["pid"] as? NSNumber)
        let pid = number.int32Value
        XCTAssertGreaterThan(pid, 0)
        XCTAssertEqual(Int64(pid), number.int64Value)
        let identity = "io.ai-station.presentation"
        let registered = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            NSRunningApplication(processIdentifier: pid)?.bundleIdentifier == identity
        }, object: nil)
        let registration = XCTWaiter.wait(for: [registered], timeout: 15)
        XCTAssertEqual(registration, .completed,
                       "Observed helper bundle: \(NSRunningApplication(processIdentifier: pid)?.bundleIdentifier ?? "none")")
        let application = try XCTUnwrap(NSRunningApplication(processIdentifier: pid))
        let helper = root.appendingPathComponent("bin/AI Station Helper.app/Contents/MacOS/ai-station-native")
        XCTAssertEqual(application.executableURL?.resolvingSymlinksInPath(), helper.resolvingSymlinksInPath())
        let proxy = XCUIApplication(bundleIdentifier: identity) // Attach; never launch a substitute.
        let dialog = proxy.dialogs.firstMatch
        XCTAssertTrue(dialog.buttons["Restore and reset MFA"].waitForExistence(timeout: 15))
        XCTAssertFalse(dialog.buttons["Restore and reset MFA"].isEnabled)
        dialog.buttons["Cancel"].click()
        XCTAssertTrue(proxy.wait(for: .notRunning, timeout: 10))
    }
}
