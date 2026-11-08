import XCTest

final class GroupShotsUITests: XCTestCase {
    private var dir: URL!
    override func setUpWithError() throws {
        continueAfterFailure = false
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/r8g3")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
    }
    @MainActor private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }
    @MainActor private func shot(_ app: XCUIApplication, _ name: String) throws {
        sleep(2)
        try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent(name + ".png"))
    }
    @MainActor private func reveal(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        let item = element(app, id)
        for _ in 0..<10 {
            if item.exists && item.isHittable { break }
            app.swipeUp()
        }
        return item
    }
    @MainActor func testGroupScreens() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakeVoice", "YES", "-mockGroups", "YES"]
        app.launch()
        XCTAssertTrue(element(app, "chat-search").waitForExistence(timeout: 15))
        let row = reveal(app, "group-13-ws_finance001-grp_t_cartax2027")
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        try shot(app, "list")
        row.tap()
        XCTAssertTrue(element(app, "group-members").waitForExistence(timeout: 10))
        try shot(app, "room-top")
        let approval = reveal(app, "group-approval")
        XCTAssertTrue(approval.exists)
        try shot(app, "room-task-approval")
        element(app, "group-members").tap()
        XCTAssertTrue(app.staticTexts["You · owner"].waitForExistence(timeout: 10))
        try shot(app, "members")
        app.buttons["Done"].tap()
        app.buttons["group-back"].tap()
        reveal(app, "group-history").tap()
        XCTAssertTrue(element(app, "group-13-ws_finance001-grp_t_cartax2026").waitForExistence(timeout: 10))
        try shot(app, "history")
    }
}
