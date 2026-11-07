import XCTest

@MainActor
final class OwnerTF1MediaUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func openPicker(extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [
            "-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
            "-openChat", "ws_pilatus001", "-fakePhoto", "NO"
        ] + (extra.isEmpty ? ["-fakeLocation", "NO"] : extra)
        app.launch()
        let general = app.buttons["general-ws_pilatus001"]
        XCTAssertTrue(general.waitForExistence(timeout: 20))
        general.tap()
        let attach = app.buttons["composer-attach"]
        XCTAssertTrue(attach.waitForExistence(timeout: 10))
        attach.tap()
        XCTAssertTrue(app.buttons["media-location"].waitForExistence(timeout: 5))
        return app
    }

    func testAttachShowsOneCompactRowOfFourChoices() {
        let app = openPicker()
        let ids = ["media-camera", "media-photos", "media-files", "media-location"]
        let choices = app.descendants(matching: .any)["media-choices"].firstMatch
        XCTAssertEqual(choices.buttons.count, 4)
        XCTAssertEqual(choices.tables.count, 0)
        XCTAssertFalse(app.buttons["media-fake-photo"].exists)
        XCTAssertFalse(app.buttons["media-fake-pdf"].exists)
        let first = app.buttons[ids[0]].frame
        var previous = first
        for (index, id) in ids.enumerated() {
            XCTAssertEqual(app.buttons.matching(identifier: id).count, 1, "No duplicate \(id)")
            let button = app.buttons[id]
            XCTAssertTrue(button.isHittable, id)
            XCTAssertEqual(button.frame.midY, first.midY, accuracy: 2, "All choices share one row")
            XCTAssertTrue(app.frame.contains(button.frame), "Choice fits on screen")
            if index > 0 { XCTAssertGreaterThanOrEqual(button.frame.minX, previous.maxX) }
            previous = button.frame
        }
        XCTAssertGreaterThan(first.minY, app.frame.minY + app.frame.height * 0.65, "Choices stay near the bottom in a compact sheet")
        XCTAssertTrue(app.buttons["media-close"].isHittable)
    }

    func testLocationShowsMapsAboveShareWithoutScrollingAndInChat() {
        let app = openPicker(extra: ["-fakeLocation", "YES"])
        app.buttons["media-location"].tap()
        let maps = app.buttons["Open in Maps"]
        XCTAssertTrue(maps.waitForExistence(timeout: 10))
        let share = app.buttons["media-send"]
        let visible = NSPredicate(format: "isHittable == true")
        wait(for: [XCTNSPredicateExpectation(predicate: visible, object: share)], timeout: 5)
        XCTAssertEqual(maps.label, "Open in Maps")
        XCTAssertTrue(maps.isHittable)
        XCTAssertTrue(app.frame.contains(maps.frame))
        XCTAssertTrue(app.frame.contains(share.frame))
        XCTAssertLessThanOrEqual(maps.frame.maxY, share.frame.minY)
        share.tap()
        wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: share)], timeout: 5)
        XCTAssertTrue(maps.waitForExistence(timeout: 15), "The sent location card also offers Maps")
        XCTAssertTrue(maps.isHittable)
    }
}
