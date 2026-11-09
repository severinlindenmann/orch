import XCTest

final class MuteUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testMuteAllAndTurnOn() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let toggle = app.switches["mute-all"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        toggle.tap()
        XCTAssertTrue(app.buttons["1 hour"].waitForExistence(timeout: 5))
        app.buttons["1 hour"].tap()
        let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == '1'"), object: toggle)
        XCTAssertEqual(XCTWaiter.wait(for: [enabled], timeout: 5), .completed)
        app.navigationBars.buttons.firstMatch.tap()
        let banner = app.descendants(matching: .any)["mute-all-banner"].firstMatch
        XCTAssertTrue(banner.waitForExistence(timeout: 5))
        app.buttons["mute-all-off"].tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: banner)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 5), .completed)
    }

    func testWorkspaceMuteShowsOnRow() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-openChat", "ws_pilatus001"]
        app.launch()
        let mute = app.buttons["chat-mute"]
        XCTAssertTrue(mute.waitForExistence(timeout: 15))
        mute.tap()
        let forever = app.buttons["Until I turn it back on"]
        XCTAssertTrue(forever.waitForExistence(timeout: 5))
        forever.tap()
        let unmuting = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == 'Unmute'"), object: mute)
        XCTAssertEqual(XCTWaiter.wait(for: [unmuting], timeout: 5), .completed)
        app.navigationBars.buttons.firstMatch.tap()
        let row = app.buttons["room-ws_pilatus001"]
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        XCTAssertTrue(row.images["Muted"].exists)
    }
}
