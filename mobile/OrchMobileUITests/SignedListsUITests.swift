import XCTest

/// ORCH-1296: the phone's questions and chat show what the workspace signed, not what the relay changed. The mock
/// relay (`-mockRelayChanged YES`) lists "Keep the old backups?" and "Deploy now." for a question and a text whose
/// signed words are "Delete the old backups?" and "Do not deploy tonight.". Screenshots go to `ORCH_SHOTS` when set.
final class SignedListsUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func has(_ app: XCUIApplication, _ text: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    private func shot(_ app: XCUIApplication, _ name: String) throws {
        let s = app.screenshot()
        let a = XCTAttachment(screenshot: s); a.name = name; a.lifetime = .keepAlways; add(a)
        if let dir = ProcessInfo.processInfo.environment["ORCH_SHOTS"], !dir.isEmpty {
            try s.pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
        }
    }

    func testQuestionsAndChatShowTheSignedWords() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockSigningKey", "YES",
                                "-mockRelayChanged", "YES", "-openChat", "ws_pilatus001"]
        app.launch()
        let accept = app.buttons["accept-workspace"]
        XCTAssertTrue(accept.waitForExistence(timeout: 15))
        XCTAssertFalse(has(app, "Deploy now.").exists, "nothing from a workspace not accepted yet")
        try shot(app, "signed-lists-before-accept")
        accept.tap()
        XCTAssertTrue(has(app, "Do not deploy tonight.").waitForExistence(timeout: 15), "the chat shows the signed text")
        XCTAssertFalse(has(app, "Deploy now.").exists, "never the relay's changed text")
        // Questions are on Chats under Needs your OK (they left the workspace screen with its topic list, ORCH-1169).
        app.navigationBars.buttons.firstMatch.tap()
        let needsYou = app.buttons["filter-Needs you"]
        XCTAssertTrue(needsYou.waitForExistence(timeout: 15))
        needsYou.tap()
        XCTAssertTrue(has(app, "Delete the old backups?").waitForExistence(timeout: 15), "the question shows the signed text")
        XCTAssertFalse(has(app, "Keep the old backups?").exists, "never the relay's changed question")
        try shot(app, "signed-lists-after-accept")
    }
}
