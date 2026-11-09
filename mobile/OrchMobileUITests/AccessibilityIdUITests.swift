import XCTest

/// Guards against SwiftUI copying a container's accessibility identifier to its children.
final class AccessibilityIdUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    @MainActor
    private func duplicateIds(in app: XCUIApplication, ignoring: Set<String> = []) -> [String: Int] {
        do {
            // Equivalent to all descendants, but fetch the accessibility tree only once.
            // Reading identifiers from live XCUIElements would query the app repeatedly.
            let snapshot = try app.snapshot()
            var counts: [String: Int] = [:]
            func visit(_ node: XCUIElementSnapshot) {
                let id = node.identifier
                // SF Symbol images carry their symbol name ("chevron.right") as identifier: not ours.
                if !id.isEmpty, !(node.elementType == .image && id.contains(".")) { counts[id, default: 0] += 1 }
                for child in node.children { visit(child) }
            }
            for child in snapshot.children { visit(child) }

            var ignored = ignoring
            for id in counts.keys {
                // SwiftUI's mangled implementation identifiers can repeat across host views.
                if id.contains("_Tt") { ignored.insert(id) }
                // System navigation back buttons can occur in multiple navigation containers.
                if id.contains("BackButton") { ignored.insert(id) }
                // Generated list-cell wrapper identifiers can repeat with their cell content.
                if id.hasSuffix("-cell") { ignored.insert(id) }
                // A workspace's badge (one element, children ignored) is shown in every row of that workspace by design.
                if id.hasPrefix("workspace-badge") { ignored.insert(id) }
            }
            return counts.filter { $0.value > 1 && !ignored.contains($0.key) }
        } catch {
            XCTFail("Could not snapshot accessibility identifiers: \(error)")
            return [:]
        }
    }

    @MainActor
    private func assertUniqueIds(in app: XCUIApplication, file: StaticString = #filePath, line: UInt = #line) {
        // Only a duplicate that STAYS is a propagation bug. During a push/pop transition both screens exist for a moment
        // and their ids appear twice (slow CI runners snapshot mid-transition): re-check until the screen settles.
        var duplicates = duplicateIds(in: app)
        let deadline = Date().addingTimeInterval(8)
        while !duplicates.isEmpty && Date() < deadline {
            usleep(500_000)
            let now = duplicateIds(in: app)
            duplicates = duplicates.filter { now[$0.key] != nil }.merging(now.filter { duplicates[$0.key] != nil }) { _, b in b }
            if now.isEmpty { duplicates = [:] }
        }
        // One line: CI's failure summary only shows the first line of a message.
        let details = duplicates.keys.sorted().map { "\($0)=\(duplicates[$0]!)" }.joined(separator: ", ")
        XCTAssertTrue(duplicates.isEmpty, "Duplicate accessibility identifiers (id=count): \(details)", file: file, line: line)
    }

    @MainActor
    private func launch(_ arguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"] + arguments
        app.launch()
        return app
    }

    @MainActor
    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    @MainActor
    private func reveal(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        let item = element(app, id)
        for _ in 0..<10 {
            if item.exists && item.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(item.waitForExistence(timeout: 10), "Missing \(id)")
        XCTAssertTrue(item.isHittable, "Could not reveal \(id)")
        return item
    }

    @MainActor
    func testChatsListHasUniqueAccessibilityIds() {
        let app = launch(["-mockGroups", "YES"])
        XCTAssertTrue(element(app, "chat-search").waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
        assertUniqueIds(in: app)
    }

    @MainActor
    func testNewChatSheetHasUniqueAccessibilityIds() {
        let app = launch()
        XCTAssertTrue(app.buttons["new-chat"].waitForExistence(timeout: 15))
        app.buttons["new-chat"].tap()
        XCTAssertTrue(element(app, "new-chat-sheet").waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["contact-ws_reports001"].waitForExistence(timeout: 5))
        assertUniqueIds(in: app)
    }

    @MainActor
    func testSettingsHasUniqueAccessibilityIds() {
        let app = launch(["-startTab", "settings"])
        XCTAssertTrue(element(app, "voice-settings").waitForExistence(timeout: 20))
        assertUniqueIds(in: app)
    }

    @MainActor
    func testTicketChatHasUniqueAccessibilityIds() {
        let app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_q3sum1"])
        XCTAssertTrue(element(app, "composer").waitForExistence(timeout: 20))
        XCTAssertTrue(element(app, "chat-title").waitForExistence(timeout: 10))
        assertUniqueIds(in: app)
    }

    @MainActor
    func testTicketReviewBarHasUniqueAccessibilityIds() {
        let app = launch(["-mockReview", "YES", "-openChat", "ws_pilatus001", "-openTicket", "t_reviewfish"])
        XCTAssertTrue(element(app, "review-bar").waitForExistence(timeout: 20))
        XCTAssertTrue(app.buttons["review-accept"].waitForExistence(timeout: 10))
        assertUniqueIds(in: app)
    }

    @MainActor
    func testGroupApprovalCardHasUniqueAccessibilityIds() {
        let app = launch(["-mockGroups", "YES"])
        XCTAssertTrue(element(app, "chat-search").waitForExistence(timeout: 15))
        reveal(app, "group-13-ws_finance001-grp_t_cartax2027").tap()
        XCTAssertTrue(element(app, "group-members").waitForExistence(timeout: 10))
        _ = reveal(app, "group-approval")
        assertUniqueIds(in: app)
    }
}
