import XCTest

/// Evidence screenshots of the workspace look (chats list, workspace screen, info). Runs only when the folder exists.
final class LookShotsUITests: XCTestCase {
    func testLookShots() throws {
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        let dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/look")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
        func run(_ name: String, _ extra: [String], wait id: String) throws {
            let app = XCUIApplication()
            app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"] + extra
            app.launch()
            XCTAssertTrue(app.descendants(matching: .any)[id].firstMatch.waitForExistence(timeout: 20), id)
            sleep(2)
            try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
            app.terminate()
        }
        try run("1-chats-list", [], wait: "workspace-badge-ws_pilatus001")
        try run("2-workspace", ["-open", "workspace:ws_pilatus001"], wait: "workspace-badge-header-ws_pilatus001")
        try run("3-info", ["-openChat", "ws_pilatus001", "-openTicket", "t_7k3f9q", "-openInfo", "YES"], wait: "workspace-badge-info-ws_pilatus001")
    }
}
