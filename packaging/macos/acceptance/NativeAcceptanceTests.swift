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

final class NativeMaintenanceAcceptanceTests: XCTestCase {
    private func fixture() throws -> [String: String] {
        let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let descriptor = repository.appendingPathComponent(".tools/mac-consumer-experiment/maintenance-paths.private.json")
        let value = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(contentsOf: descriptor)) as? [String: String])
        let state = try XCTUnwrap(value["state"])
        XCTAssertTrue(state.hasSuffix("/Library/Application Support/AI Station"))
        return value
    }

    private func click(_ label: String, timeout: TimeInterval = 60) throws {
        let state = try XCTUnwrap(try fixture()["state"])
        let identity = "io.ai-station.presentation"
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            let owners = NSRunningApplication.runningApplications(withBundleIdentifier: identity)
            if owners.count == 1, let owner = owners.first {
                // Preparation and each dialog are distinct processes. Reattach
                // while waiting; never pin a completed progress window's PID.
                let app = XCUIApplication(bundleIdentifier: identity)
                let button = app.dialogs.firstMatch.buttons[label]
                if button.exists && button.isEnabled {
                    let executable = try XCTUnwrap(owner.executableURL?.resolvingSymlinksInPath().path)
                    let retained = URL(fileURLWithPath: state).appendingPathComponent("releases").path
                    XCTAssertTrue(executable.hasPrefix(retained + "/"))
                    XCTAssertTrue(executable.hasSuffix("/bin/AI Station Helper.app/Contents/MacOS/ai-station-native"))
                    button.click()
                    let closed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in owner.isTerminated }, object: nil)
                    XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 15), .completed)
                    return
                }
            }
            Thread.sleep(forTimeInterval: 1)
        } while Date() < deadline
        XCTFail("The retained helper did not present the expected maintenance action: \(label)")
    }

    func testCreateCompleteBackup() throws {
        continueAfterFailure = false
        executionTimeAllowance = 480
        try click("Create backup") // Selection, followed by the ordinary explicit confirmation.
        try click("Create backup")
        try click("Open AI Station", timeout: 300) // Do not export a path or open Finder.
    }

    func testRestoreCompleteBackup() throws {
        continueAfterFailure = false
        executionTimeAllowance = 480
        let value = try fixture()
        let path = try XCTUnwrap(value["backup"])
        let state = try XCTUnwrap(value["state"])
        let exports = URL(fileURLWithPath: state).appendingPathComponent("database-exports").path
        XCTAssertEqual(URL(fileURLWithPath: path).deletingLastPathComponent().path, exports)
        XCTAssertNotNil(UUID(uuidString: URL(fileURLWithPath: path).lastPathComponent))
        try click("Restore backup…")
        let picker = XCUIApplication(bundleIdentifier: "io.ai-station.presentation")
        let panel = picker.dialogs["open-panel"]
        XCTAssertTrue(panel.buttons["Check backup"].waitForExistence(timeout: 30))
        picker.typeKey("g", modifierFlags: [.command, .shift])
        let location = picker.sheets.textFields.firstMatch
        XCTAssertTrue(location.waitForExistence(timeout: 15))
        location.typeText(path + "\n")
        XCTAssertTrue(panel.buttons["Check backup"].isEnabled)
        panel.buttons["Check backup"].click()
        try click("Restore backup", timeout: 90) // Keep current password; no exceptional MFA reset.
        try click("Open AI Station", timeout: 300)
    }
}

final class NativeConsumerAcceptanceTests: XCTestCase {
    func testActualFirstLaunchAndBrowserAdministratorSetup() throws {
        continueAfterFailure = false
        executionTimeAllowance = 1200
        let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let root = repository.appendingPathComponent(".tools/mac-consumer-experiment")
        let descriptor = try Data(contentsOf: root.appendingPathComponent("gui-process.json"))
        let value = try XCTUnwrap(try JSONSerialization.jsonObject(with: descriptor) as? [String: Any])
        let number = try XCTUnwrap(value["pid"] as? NSNumber)
        XCTAssertGreaterThan(number.int32Value, 0)
        XCTAssertEqual(Int64(number.int32Value), number.int64Value)
        let main = try XCTUnwrap(NSRunningApplication(processIdentifier: number.int32Value))
        XCTAssertEqual(main.executableURL?.resolvingSymlinksInPath(),
                       root.appendingPathComponent("AI Station.app/Contents/MacOS/AI Station").resolvingSymlinksInPath())
        let helper = XCUIApplication(bundleIdentifier: "io.ai-station.presentation")
        let setup = helper.dialogs.firstMatch.buttons["Set up AI Station"]
        XCTAssertTrue(setup.waitForExistence(timeout: 90))
        setup.click() // Ordinary stock consent, never a hidden auto-approval flag.

        let handler = try XCTUnwrap(NSWorkspace.shared.urlForApplication(toOpen: URL(string: "http://127.0.0.1")!))
        let identity = try XCTUnwrap(Bundle(url: handler)?.bundleIdentifier)
        let browser = XCUIApplication(bundleIdentifier: identity) // Attach to the browser opened by the product.
        // The browser opens after package retention, bridge, database and API
        // startup, each with its own bounded operation. Include that whole path.
        let deadline = Date().addingTimeInterval(900)
        while browser.state != .runningForeground && Date() < deadline {
            if helper.state != .notRunning {
                let close = helper.dialogs.firstMatch.buttons["Close"]
                if close.exists {
                    close.click() // Acknowledge the product's actual startup error before cleanup.
                    XCTFail("The installed app displayed a startup error before browser readiness")
                    return
                }
            }
            _ = browser.wait(for: .runningForeground, timeout: 1)
        }
        XCTAssertEqual(browser.state, .runningForeground)
        let page = browser.webViews.firstMatch
        let username = page.textFields["Username"]
        XCTAssertTrue(username.waitForExistence(timeout: 60))
        XCTAssertTrue(username.isEnabled)
        XCTAssertEqual(page.secureTextFields.count, 2)
        username.click()
        // First setup intentionally suggests "admin". Replace it as a user
        // would; appending creates a different valid account than the observer
        // subsequently tries to authenticate.
        username.typeKey("a", modifierFlags: .command)
        username.typeText("QaAdmin")
        XCTAssertEqual(username.value as? String, "QaAdmin")
        page.secureTextFields.element(boundBy: 0).click()
        page.secureTextFields.element(boundBy: 0).typeText("synthetic private desktop acceptance password")
        page.secureTextFields.element(boundBy: 1).click()
        page.secureTextFields.element(boundBy: 1).typeText("synthetic private desktop acceptance password")
        page.buttons["Create your account"].click()
        XCTAssertTrue(page.buttons["Sign out"].waitForExistence(timeout: 30))
        // First sign-in may open the ordinary conversation. Follow the same
        // visible Models navigation as a user instead of assuming a redirect.
        if !page.staticTexts["Set up your models"].exists {
            page.links["Models"].click()
            let setupModels = page.links.matching(NSPredicate(
                format: "label BEGINSWITH %@", "Set up a local model"
            )).firstMatch
            XCTAssertTrue(setupModels.waitForExistence(timeout: 30))
            setupModels.click()
        }
        XCTAssertTrue(page.staticTexts["Set up your models"].waitForExistence(timeout: 30))
    }
}

final class NativeGuidedAcceptanceTests: XCTestCase {
    private func existingPage() throws -> XCUIElement {
        continueAfterFailure = false
        executionTimeAllowance = 420
        let handler = try XCTUnwrap(NSWorkspace.shared.urlForApplication(toOpen: URL(string: "http://127.0.0.1")!))
        let identity = try XCTUnwrap(Bundle(url: handler)?.bundleIdentifier)
        let browser = XCUIApplication(bundleIdentifier: identity)
        XCTAssertNotEqual(browser.state, .notRunning, "The product must have opened the browser")
        browser.activate() // Only the already-running product browser; no replacement URL or app.
        let page = browser.webViews.firstMatch
        XCTAssertTrue(page.waitForExistence(timeout: 30))
        return page
    }

    func testPrepareNativeEngine() throws {
        let page = try existingPage()
        let consent = page.checkBoxes.matching(NSPredicate(
            format: "label CONTAINS %@", "runtime and bundled component licenses"
        )).firstMatch
        XCTAssertTrue(consent.waitForExistence(timeout: 30))
        consent.click()
        let prepare = page.buttons["Prepare llama.cpp"]
        XCTAssertTrue(prepare.isEnabled)
        prepare.click() // The parent independently verifies the ordinary queued Run.
    }

    func testDownloadSelectedStarter() throws {
        let page = try existingPage()
        XCTAssertTrue(page.staticTexts["Native engine available"].waitForExistence(timeout: 30))
        let choice = page.radioButtons["Choose Q4_K_M"]
        XCTAssertTrue(choice.waitForExistence(timeout: 30))
        choice.click()
        let consent = page.checkBoxes.matching(NSPredicate(
            format: "label CONTAINS %@", "and want to download these files."
        )).firstMatch
        XCTAssertTrue(consent.waitForExistence(timeout: 30))
        consent.click()
        let download = page.buttons["Download 2.33 GiB"] // Fixed reviewed 2,497,281,312-byte model.
        XCTAssertTrue(download.isEnabled)
        download.click() // No API POST, injected state, hidden consent or synthetic result.
    }

    func testFirstModelAnswer() throws {
        let page = try existingPage()
        let open = page.buttons.matching(identifier: "Open Chat with this model").firstMatch
        XCTAssertTrue(open.waitForExistence(timeout: 30))
        open.click()
        let message = page.textViews["Message"]
        XCTAssertTrue(message.waitForExistence(timeout: 30))
        message.click()
        message.typeText("What is 2+2? Reply only with the number. /no_think")
        let send = page.buttons["Send"]
        XCTAssertTrue(send.isEnabled)
        send.click()
        let copy = page.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Copy AI Station ")).firstMatch
        let answer = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            copy.exists && copy.isEnabled
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [answer], timeout: 360), .completed,
                       "A real, nonempty model answer must be visible in the conversation")
    }

    func testStopStreamingAnswer() throws {
        let page = try existingPage()
        let copies = page.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Copy AI Station "))
        let previousAnswers = copies.count
        XCTAssertGreaterThan(previousAnswers, 0, "The real first answer must precede this follow-up")
        let message = page.textViews["Message"]
        XCTAssertTrue(message.waitForExistence(timeout: 30))
        message.click()
        message.typeText("Tell a fictional fairy tale about an owl visiting the moon, in at least 1000 words. /no_think")
        XCTAssertTrue(page.buttons["Send"].isEnabled)
        page.buttons["Send"].click()
        let stop = page.buttons["Stop"]
        let streaming = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            copies.count == previousAnswers + 1 && copies.element(boundBy: previousAnswers).isEnabled
                && stop.exists && stop.isEnabled
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [streaming], timeout: 180), .completed,
                       "Nonempty generated text and Stop must coexist; a queued or finished reply is insufficient")
        stop.click() // Only the ordinary visible Stop; no API cancellation substitute.
        let idle = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            !stop.exists && page.buttons["Send"].exists && message.isEnabled
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [idle], timeout: 60), .completed,
                       "The composer must become usable again after Stop")
    }
}
