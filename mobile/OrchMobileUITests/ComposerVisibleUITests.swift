import XCTest

/// The floating composer (#254) must come back after every sheet or cover: its text field and mic stay hittable after dismissing
/// the + sheet, the location sheet and the artifact viewer, in General and in a topic, at default and XXL text, keyboard closed.
/// MockRelay only (`-fakeLocation YES` stands in for the location permission).
@MainActor
final class ComposerVisibleUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ extra: [String], size: String?) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakePhoto", "YES", "-fakeLocation", "YES"] + extra
        if let size { app.launchArguments += ["-UIPreferredContentSizeCategoryName", size] }
        app.launch()
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    private func assertComposerHittable(_ app: XCUIApplication, _ when: String, file: StaticString = #filePath, line: UInt = #line) {
        let field = el(app, "composer-field"), mic = el(app, "composer-mic"), plus = el(app, "composer-attach")
        XCTAssertTrue(field.waitForExistence(timeout: 15), "text field exists \(when)", file: file, line: line)
        for (name, e) in [("text field", field), ("mic", mic), ("plus", plus)] {
            let hittable = NSPredicate(format: "isHittable == true")
            let r = XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: hittable, object: e)], timeout: 10)
            XCTAssertEqual(r, .completed, "\(name) hittable \(when)", file: file, line: line)
            XCTAssertTrue(app.frame.contains(e.frame), "\(name) on screen \(when)", file: file, line: line)
        }
        XCTAssertFalse(app.keyboards.firstMatch.exists, "keyboard closed \(when)", file: file, line: line)
    }

    private func plusAndLocation(_ app: XCUIApplication, _ where_: String) {
        assertComposerHittable(app, "at start of \(where_)")
        el(app, "composer-attach").tap()
        XCTAssertTrue(app.buttons["media-close"].waitForExistence(timeout: 10))
        app.buttons["media-close"].tap()
        XCTAssertTrue(app.buttons["media-close"].waitForNonExistence(timeout: 10))
        assertComposerHittable(app, "after closing the + sheet in \(where_)")
        el(app, "composer-attach").tap()
        let loc = app.buttons["media-location"]
        XCTAssertTrue(loc.waitForExistence(timeout: 10)); loc.tap()
        let share = app.buttons["media-send"]
        XCTAssertTrue(share.waitForExistence(timeout: 15))
        app.buttons["media-close"].tap()
        XCTAssertTrue(share.waitForNonExistence(timeout: 10))
        assertComposerHittable(app, "after dismissing the location sheet in \(where_)")
    }

    private func run(size: String?) {
        let label = size ?? "default"
        var app = launch(["-openChat", "ws_pilatus001"], size: size)
        let general = app.buttons["general-ws_pilatus001"]
        XCTAssertTrue(general.waitForExistence(timeout: 20)); general.tap()
        plusAndLocation(app, "General (\(label))")
        app.terminate()

        app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_q3sum1"], size: size)
        plusAndLocation(app, "topic (\(label))")
        let card = el(app, "artifact-a_bbbbbbbbbbbb")
        XCTAssertTrue(card.waitForExistence(timeout: 20)); card.tap()
        let close = app.buttons["artifact-close"]
        XCTAssertTrue(close.waitForExistence(timeout: 15)); close.tap()
        XCTAssertTrue(close.waitForNonExistence(timeout: 10))
        assertComposerHittable(app, "after closing the artifact viewer in the topic (\(label))")
        app.terminate()
    }

    func testComposerSurvivesSheetsAtDefaultSize() { run(size: nil) }
    func testComposerSurvivesSheetsAtXXL() { run(size: "UICTContentSizeCategoryXXL") }
}
