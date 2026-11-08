import XCTest

/// e2e P4.3: the group approval card is one container element and its answer buttons are found inside it.
final class GroupApprovalUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    @MainActor func testApprovalCardButtonsAreInsideTheCard() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockGroups", "YES"]
        app.launch()
        let any = { (id: String) in app.descendants(matching: .any)[id].firstMatch }
        XCTAssertTrue(any("chat-search").waitForExistence(timeout: 15))
        let row = any("group-13-ws_finance001-grp_t_cartax2027")
        for _ in 0..<6 where !(row.exists && row.isHittable) { app.swipeUp() }
        XCTAssertTrue(row.waitForExistence(timeout: 10)); row.tap()
        let card = any("group-approval")
        for _ in 0..<8 where !card.buttons["Allow once"].isHittable { any("group-messages").swipeUp() }
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "group-approval").count, 1, "the card is one element")
        for label in ["Allow once", "Always", "No"] {
            XCTAssertTrue(card.buttons[label].exists, "\(label) inside the card")
        }
        XCTAssertTrue(card.buttons["Allow once"].isHittable)
    }
}
