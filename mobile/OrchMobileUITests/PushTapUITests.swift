import XCTest

/// Push tap from the background and from a terminated app (the UX3 SIGABRT blocker).
/// Needs an outside `xcrun simctl push`, so it only runs when `TEST_RUNNER_ORCH_PUSH_TAP=1` is set
/// (see mobile/scripts/push-tap-check.sh). The script pushes whenever the file named in
/// `ORCH_PUSH_READY_FILE` appears; the test then taps the banner and expects the focused question.
final class PushTapUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launchPaired(_ app: XCUIApplication) {
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedNotify", "YES"]
        app.launch()
        let allow = app.buttons["Allow notifications"]
        XCTAssertTrue(allow.waitForExistence(timeout: 15))
        allow.tap()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let ok = springboard.buttons["Allow"]
        if ok.waitForExistence(timeout: 5) { ok.tap() }
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
    }

    private func waitForPushAndTap() {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        FileManager.default.createFile(atPath: "/tmp/orch-push-ready", contents: Data())
        let banner = springboard.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS 'Which date format' OR identifier == 'NotificationShortLookView'")).firstMatch
        if !banner.waitForExistence(timeout: 30) { print("SPRINGBOARD:", springboard.debugDescription) }
        XCTAssertTrue(banner.exists, "no banner")
        banner.tap()
    }

    private func requireOptIn() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["ORCH_PUSH_TAP"] == "1", "needs scripts/push-tap-check.sh")
    }

    func testTapFromBackground() throws {
        try requireOptIn()
        let app = XCUIApplication()
        launchPaired(app)
        XCUIDevice.shared.press(.home)
        waitForPushAndTap()
        XCTAssertTrue(app.buttons["answer-DATE"].waitForExistence(timeout: 15), "app did not come back focused on the question")
    }

    func testTapFromTerminated() throws {
        try requireOptIn()
        let app = XCUIApplication()
        launchPaired(app)
        app.terminate()
        waitForPushAndTap()
        // The system relaunches the app without the mock launch arguments, so only the tab can be asserted here
        // (the focused card itself is covered by PushTests.testTapBeforeModelExistsIsKeptForLater).
        let cold = XCUIApplication(bundleIdentifier: "io.severin.orch")
        XCTAssertTrue(cold.wait(for: .runningForeground, timeout: 30), "app did not come to the foreground")
        let questionsTab = cold.buttons["Chats"]
        if !questionsTab.waitForExistence(timeout: 20) { print("COLD:", cold.debugDescription) }
        XCTAssertTrue(questionsTab.exists)
        XCTAssertTrue(questionsTab.isSelected, "cold start did not open the Chats tab")
    }
}
