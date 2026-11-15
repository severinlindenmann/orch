import XCTest

/// Guards against SwiftUI copying a container's accessibility identifier to its children.
final class AccessibilityIdUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    @MainActor
    private func duplicateIds(in root: XCUIElement, ignoring: Set<String> = []) -> [String: Int] {
        do {
            // Equivalent to all descendants, but fetch the accessibility tree only once.
            // Reading identifiers from live XCUIElements would query the app repeatedly.
            let snapshot = try root.snapshot()
            var counts: [String: Int] = [:]
            func visit(_ node: XCUIElementSnapshot, barIds: Set<String>? = nil) {
                let id = node.identifier
                // Inside the navigation bar: the ids of the enclosing elements (nil outside the bar).
                var barIds = node.elementType == .navigationBar ? Set<String>() : barIds
                // iOS 26 wraps each toolbar item in a host that carries the item's id around the same control: one control,
                // not a copy. Only inside the navigation bar, so a container id copied onto its children elsewhere still fails.
                let toolbarHost = barIds?.contains(id) == true
                // SF Symbol images carry their symbol name ("chevron.right") as identifier: not ours.
                if !id.isEmpty, !toolbarHost, !(node.elementType == .image && id.contains(".")) { counts[id, default: 0] += 1 }
                if !id.isEmpty { barIds?.insert(id) }
                for child in node.children { visit(child, barIds: barIds) }
            }
            // An app snapshot starts below the application; an element snapshot includes the element itself.
            if root.elementType == .application { for child in snapshot.children { visit(child) } } else { visit(snapshot) }

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
    private func assertUniqueIds(in app: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        let duplicates = duplicateIds(in: app)
        // One line: CI's failure summary only shows the first line of a message.
        let details = duplicates.keys.sorted().map { "\($0)=\(duplicates[$0]!)" }.joined(separator: ", ")
        XCTAssertTrue(duplicates.isEmpty, "Duplicate accessibility identifiers (id=count): \(details)", file: file, line: line)
    }

    /// -openTicket PUSHES the ticket chat over the workspace chat: until that transition is over both screens exist and
    /// every id appears twice. Wait for the end of the push (exactly one conversation screen, the ticket's status line
    /// hittable), then take ONE snapshot.
    @MainActor
    private func waitForTicketChatSettled(_ app: XCUIApplication, file: StaticString = #filePath, line: UInt = #line) {
        let screens = app.descendants(matching: .any).matching(identifier: "conversation-view")
        let one = XCTNSPredicateExpectation(predicate: NSPredicate(format: "count == 1"), object: screens)
        XCTAssertEqual(XCTWaiter.wait(for: [one], timeout: 20), .completed, "one conversation screen after the push", file: file, line: line)
        let status = element(app, "tasks-toggle")
        let hittable = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == true AND hittable == true"), object: status)
        XCTAssertEqual(XCTWaiter.wait(for: [hittable], timeout: 20), .completed, "ticket status line hittable", file: file, line: line)
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
        XCTAssertTrue(app.buttons["nt-mic"].waitForExistence(timeout: 5))   // + opens New topic directly
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
        waitForTicketChatSettled(app)
        assertUniqueIds(in: app)
    }

    @MainActor
    func testTicketReviewBarHasUniqueAccessibilityIds() {
        let app = launch(["-mockReview", "YES", "-openChat", "ws_pilatus001", "-openTicket", "t_reviewfish"])
        XCTAssertTrue(element(app, "review-bar").waitForExistence(timeout: 20))
        XCTAssertTrue(app.buttons["review-accept"].waitForExistence(timeout: 10))
        waitForTicketChatSettled(app)
        assertUniqueIds(in: app)
    }

    @MainActor
    func testGroupApprovalCardHasUniqueAccessibilityIds() {
        // Open the room directly (-open group:…): no list swiping and no match-anything query over the big Chats list, which timed
        // out on slow CI runners ("Failed to get matching snapshots"). The card is found by its own type, then snapshotted alone.
        let app = launch(["-mockGroups", "YES", "-open", "group:ws_finance001:grp_t_cartax2027"])
        XCTAssertTrue(app.otherElements["group-members"].waitForExistence(timeout: 30) || app.buttons["group-members"].exists || app.descendants(matching: .any)["group-members"].waitForExistence(timeout: 10), "room open")
        // The room opens at the newest message; the approval card is earlier: scroll back up until it is on screen.
        for _ in 0..<8 where !app.buttons["Allow once"].exists { app.otherElements["group-messages"].firstMatch.swipeDown() }
        let card = app.otherElements["group-approval"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 15), "group-approval card")
        assertUniqueIds(in: card)
    }
}
