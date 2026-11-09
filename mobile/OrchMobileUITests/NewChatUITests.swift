import XCTest

final class NewChatUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testSearchContactOpensChat() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
        app.buttons["new-chat"].tap()
        let sheet = app.descendants(matching: .any)["new-chat-sheet"].firstMatch
        XCTAssertTrue(sheet.waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["contact-ws_reports001"].exists)
        let search = app.textFields["contact-search"]
        search.tap()
        expectKeyboardFocus(search)
        search.typeText("pil")
        let pilatus = app.buttons["contact-ws_pilatus001"]
        XCTAssertTrue(pilatus.waitForExistence(timeout: 5))
        let reports = app.buttons["contact-ws_reports001"]
        let removed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: reports)
        XCTAssertEqual(XCTWaiter.wait(for: [removed], timeout: 5), .completed)
        search.tap()
        search.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 3))
        XCTAssertTrue(reports.waitForExistence(timeout: 5))
        XCTAssertTrue(reports.staticTexts["Chat"].exists)
        XCTAssertTrue(reports.label.contains("Chat"))
        pilatus.tap()
        XCTAssertTrue(app.descendants(matching: .any)["chat-title"].firstMatch.waitForExistence(timeout: 10))
        XCTAssertFalse(sheet.exists)
    }
}
