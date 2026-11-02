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
        // The supervisor launches a nested binary directly, with a private pipe,
        // rather than launching the app's main executable through Launch Services.
        // Verify that exact process/bundle boundary before full-package UI tests.
        // Use the standalone product compile. The Xcode app executable is signed
        // against its original Info.plist and cannot be transplanted as a helper.
        let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let source = repository.appendingPathComponent(".native-mac/ui-acceptance/ai-station-native")

        let files = FileManager.default
        let scratch = files.temporaryDirectory.appendingPathComponent("ai-station-native-ui-\(UUID().uuidString)")
        try files.createDirectory(at: scratch, withIntermediateDirectories: false,
                                  attributes: [.posixPermissions: 0o700])
        let contents = scratch.appendingPathComponent("Helper.app/Contents")
        let helper = contents.appendingPathComponent("Resources/bin/ai-station-native")
        try files.createDirectory(at: helper.deletingLastPathComponent(), withIntermediateDirectories: true,
                                  attributes: [.posixPermissions: 0o700])
        try files.createDirectory(at: contents.appendingPathComponent("MacOS"), withIntermediateDirectories: true)
        try files.copyItem(at: source, to: helper)
        try files.copyItem(at: source, to: contents.appendingPathComponent("MacOS/Helper"))
        let identity = "org.ai-station.qa.NestedHelper"
        let info: [String: Any] = ["CFBundleExecutable": "Helper", "CFBundleIdentifier": identity,
                                   "CFBundleName": "AI Station QA", "CFBundlePackageType": "APPL",
                                   "NSPrincipalClass": "NSApplication"]
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
            .write(to: contents.appendingPathComponent("Info.plist"))

        let child = Process()
        child.executableURL = helper
        child.arguments = ["--native-admin-recovery"]
        child.standardOutput = FileHandle.nullDevice
        child.standardError = FileHandle.nullDevice
        child.environment = ProcessInfo.processInfo.environment.filter {
            ["HOME", "TMPDIR", "LANG", "PATH", "__CF_USER_TEXT_ENCODING"].contains($0.key)
        }
        let finished = expectation(description: "Owned presentation child exited")
        child.terminationHandler = { _ in finished.fulfill() }
        try child.run()
        addTeardownBlock { if child.isRunning { child.terminate() } }
        let registered = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            NSRunningApplication(processIdentifier: child.processIdentifier)?.bundleIdentifier == identity
        }, object: nil)
        let registration = XCTWaiter.wait(for: [registered], timeout: 15)
        XCTAssertEqual(registration, .completed,
                       "Observed helper bundle: \(NSRunningApplication(processIdentifier: child.processIdentifier)?.bundleIdentifier ?? "none")")
        let application = try XCTUnwrap(NSRunningApplication(processIdentifier: child.processIdentifier))
        XCTAssertEqual(application.executableURL?.resolvingSymlinksInPath(), helper.resolvingSymlinksInPath())
        let proxy = XCUIApplication(bundleIdentifier: identity) // Attach; never launch a substitute.
        let dialog = proxy.dialogs.firstMatch
        XCTAssertTrue(dialog.buttons["Restore and reset MFA"].waitForExistence(timeout: 15))
        XCTAssertFalse(dialog.buttons["Restore and reset MFA"].isEnabled)
        dialog.buttons["Cancel"].click()
        wait(for: [finished], timeout: 10)
        XCTAssertEqual(child.terminationStatus, 0)
        try files.removeItem(at: scratch)
    }
}
