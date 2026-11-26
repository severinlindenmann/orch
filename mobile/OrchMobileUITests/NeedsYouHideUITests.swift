import XCTest

final class NeedsYouHideUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func firstQuestionRow(_ app: XCUIApplication) -> XCUIElement {
        let predicate = NSPredicate(format: "identifier BEGINSWITH 'needs-you-' AND NOT identifier BEGINSWITH 'needs-you-hide' AND identifier != 'needs-you-see-all' AND identifier != 'needs-you-hidden'")
        return app.descendants(matching: .any).matching(predicate).firstMatch
    }

    func testSwipeHidesQuestionAndUndoRestoresIt() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockAllow", "YES"]   // plain questions are Review stack cards (M5); a permission ask stays in Needs your OK
        app.launchEnvironment["ORCH_UITEST_TOAST_SECONDS"] = "30"   // a slow CI runner: the toast must still be there to tap Undo
        app.launch()
        let row = firstQuestionRow(app)
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        let id = row.identifier
        // A long drag across the row (from the right edge to the left edge): past the 55% "hide at once" mark, whatever the
        // swipe speed of this simulator. swipeLeft() alone can stop short and only reveal the Hide button.
        let start = row.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5))
        let end = row.coordinate(withNormalizedOffset: CGVector(dx: 0.02, dy: 0.5))
        start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .default, thenHoldForDuration: 0)
        // The Undo button is the toast's own control: it is what a person taps (the toast lives 5 s).
        let undo = app.buttons["hidden-undo"]
        XCTAssertTrue(undo.waitForExistence(timeout: 5), "the Hidden · Undo toast shows")
        XCTAssertFalse(app.descendants(matching: .any)[id].firstMatch.waitForExistence(timeout: 1), "row left the pinned section")
        undo.tap()
        XCTAssertTrue(app.descendants(matching: .any)[id].firstMatch.waitForExistence(timeout: 5), "Undo brings the row back")
    }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockAllow", "YES"]
        app.launchEnvironment["ORCH_UITEST_TOAST_SECONDS"] = "30"
        app.launch()
        return app
    }
    /// A slow drag over about a third of the row: past the 40 pt reveal mark, short of "hide at once", no fling.
    private func shortSwipe(_ row: XCUIElement) {
        row.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5))
            .press(forDuration: 0.05, thenDragTo: row.coordinate(withNormalizedOffset: CGVector(dx: 0.55, dy: 0.5)), withVelocity: .slow, thenHoldForDuration: 0.1)
    }
    private func settles(_ row: XCUIElement, at x: CGFloat, _ what: String, file: StaticString = #filePath, line: UInt = #line) {
        let at = NSPredicate { el, _ in abs(((el as? XCUIElement)?.frame.minX ?? .infinity) - x) < 4 }
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: at, object: row)], timeout: 5), .completed,
                       "\(what): row at x=\(x), is at \(row.frame.minX)", file: file, line: line)
    }

    /// Reveal, cancel and commit by the button; runs the same with Reduce Motion on or off (the row only stops animating).
    func testShortSwipeRevealsHideTapClosesAndHideButtonHides() {
        let app = launch()
        let row = firstQuestionRow(app)
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        let id = row.identifier
        let home = row.frame.minX
        shortSwipe(row)
        settles(row, at: home - 96, "a short swipe reveals the 96 pt Hide button")
        XCTAssertFalse(app.buttons["hidden-undo"].exists, "a short swipe does not hide")
        row.tap()   // a tap on the open row closes it and does not open the chat
        settles(row, at: home, "a tap closes the row")
        XCTAssertTrue(app.descendants(matching: .any)[id].firstMatch.isHittable, "still on Chats, the row is back in place")
        shortSwipe(row)
        settles(row, at: home - 96, "the row opens again")
        let window = app.windows.firstMatch.frame
        app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: window.maxX - 48, dy: row.frame.midY)).tap()
        XCTAssertTrue(app.buttons["hidden-undo"].waitForExistence(timeout: 5), "the Hide button hides it, with Undo")
        XCTAssertFalse(app.descendants(matching: .any)[id].firstMatch.waitForExistence(timeout: 1), "row left the pinned section")
    }

    /// Turns Reduce Motion on and off in the Settings app while orch stays open, swiping in between. Drives the simulator's
    /// own Settings, so local evidence only (`TEST_RUNNER_ORCH_UITEST_SETTINGS=1`), with a screen recording running beside it.
    func testReduceMotionChangedWhileTheAppIsOpen() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["ORCH_UITEST_SETTINGS"] == "1", "drives Settings: set TEST_RUNNER_ORCH_UITEST_SETTINGS=1")
        let app = launch()
        let row = firstQuestionRow(app)
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        let home = row.frame.minX
        func cycle() {
            shortSwipe(row); settles(row, at: home - 96, "reveal"); sleep(2)
            row.tap(); settles(row, at: home, "close"); sleep(2)
        }
        cycle()
        for _ in 0..<2 {
            let settings = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
            settings.launch()
            for name in ["Accessibility", "Motion"] {
                let cell = settings.staticTexts[name].firstMatch
                for _ in 0..<4 where !cell.isHittable { settings.swipeUp() }
                cell.tap()
            }
            let toggle = settings.switches["Reduce Motion"].firstMatch
            XCTAssertTrue(toggle.waitForExistence(timeout: 5))
            let was = toggle.value as? String
            toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap()   // the switch knob, not the row's label
            let flipped = NSPredicate { el, _ in ((el as? XCUIElement)?.value as? String) != was }
            XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: flipped, object: toggle)], timeout: 5), .completed,
                           "Reduce Motion changed from \(was ?? "?")")
            app.activate()
            XCTAssertTrue(row.waitForExistence(timeout: 5))
            sleep(1)
            cycle()
        }
    }
}
