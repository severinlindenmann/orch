import XCTest

/// Pictures of Accept and the phone's fingerprint for the owner's review card (ORCH-1204). Runs only when the
/// shots folder exists (build/shots in the worktree, passed as SHOTS_DIR in the test environment).
final class AcceptShotsUITests: XCTestCase {
    private var dir: URL!
    override func setUpWithError() throws {
        continueAfterFailure = false
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        dir = URL(fileURLWithPath: home).appendingPathComponent("orch-wt/orch-1204-phone-signing/build/shots")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
    }
    private func launch(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"] + extra
        app.launch()
        return app
    }
    private func shot(_ app: XCUIApplication, _ name: String) throws {
        sleep(2)
        try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
    }

    func testShots() throws {
        var app = launch(["-openChat", "ws_pilatus001"])
        sleep(4)
        try shot(app, "workspace-before"); app.terminate()

        app = launch(["-openChat", "ws_pilatus001", "-mockSigningKey", "YES"])
        let card = app.descendants(matching: .any)["accept-fingerprint"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 15))
        try shot(app, "workspace-accept-card")
        app.buttons["accept-workspace"].tap()
        XCTAssertTrue(card.waitForNonExistence(timeout: 5))
        try shot(app, "workspace-after-accept"); app.terminate()

        app = launch(["-startTab", "settings"])
        let fp = app.descendants(matching: .any)["phone-fingerprint"].firstMatch
        for _ in 0..<6 where !fp.isHittable { app.swipeUp() }
        XCTAssertTrue(fp.exists)
        try shot(app, "settings-fingerprint"); app.terminate()
    }
}
