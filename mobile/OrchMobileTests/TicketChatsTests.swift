import XCTest
@testable import OrchMobile

/// Team chat step 1 in the app: the Ticket chats list on Chats and names in a ticket chat (ORCH-1169).
final class TicketChatsTests: XCTestCase {
    private func ticket(_ t: String, view: TicketSnapshot? = nil, status: Ticket.Status = .working, at: String = "2026-11-21T09:00:00Z") -> Ticket {
        var x = Ticket(id: "ws_a|\(t)", workspace: "ws_a", workspaceName: "Marketing", ticket: t, title: "Launch", text: "Working on it",
                       status: status, kind: "working", at: at, question: nil)
        x.key = "MKT-7"; x.view = view
        return x
    }

    // MARK: History lines carry chat, id and name

    func testHistoryLineDecodesChatIdAndTypedName() throws {
        let json = #"{"history_tail":[{"at":"2026-11-21T09:01:00Z","who":"you","role":"person","text":"Keep the old colours","chat":true,"id":"m_a1b2c3d4e5f6g7h8","name":" Nina​  Weber "},{"at":"2026-11-21T09:00:00Z","who":"Claude","role":"agent","text":"Finished a task: Draft","name":"Ignored"}]}"#
        let view = try JSONCoding.decoder.decode(TicketSnapshot.self, from: Data(json.utf8))
        XCTAssertEqual(view.historyTail.count, 2)
        guard view.historyTail.count == 2 else { return }
        XCTAssertTrue(view.historyTail[0].chat)
        XCTAssertEqual(view.historyTail[0].messageId, "m_a1b2c3d4e5f6g7h8")
        XCTAssertEqual(view.historyTail[0].name, "Nina Weber", "invisible characters and extra spaces are cleaned on the phone too")
        XCTAssertFalse(view.historyTail[1].chat)
        XCTAssertNil(view.historyTail[1].name, "only a chat line carries a typed name")
        // Round trip (the phone stores snapshots).
        let again = try JSONCoding.decoder.decode(TicketSnapshot.self, from: JSONCoding.encoder.encode(view))
        XCTAssertEqual(again.historyTail, view.historyTail)
    }

    func testChatNamesClean() {
        XCTAssertNil(ChatNames.clean("  \n "))
        XCTAssertEqual(ChatNames.clean("Lea\nBrunner"), "Lea Brunner")
        XCTAssertEqual(ChatNames.clean(String(repeating: "x", count: 80))?.count, ChatNames.maxLength)
    }

    // MARK: Ticket chat items

    func testOlderChatLinesStayWhenNewerOnesPushThemOutOfTheWindow() {
        // #2372: the snapshot window keeps only the newest chat lines; lines from the computer seen before stay.
        func line(_ n: Int) -> TicketSnapshot.Line {
            .init(at: "2026-11-21T09:0\(n):00Z", by: "you", role: "person", text: "Line \(n)", chat: true, messageId: "m_keep00000000000\(n)", name: "Nina")
        }
        func update(_ id: String, _ lines: [TicketSnapshot.Line]) -> TicketUpdate {
            TicketUpdate(id: id, workspace: "ws_a", workspaceName: "Marketing", ticket: "t_1", kind: "note", title: "Launch", text: "",
                         replyTo: nil, at: lines.last!.at!, ticketView: TicketSnapshot(historyTail: lines))
        }
        let worked = TicketSnapshot.Line(at: "2026-11-21T09:00:30Z", by: "Claude", role: "agent", text: "Finished a task: Draft")
        let tickets = TicketBuilder.build(updates: [update("u1", [worked, line(1), line(2)]), update("u2", [line(2), line(3)])],
                                          questions: [], answers: [:])
        let items = ConversationBuilder.items(.topic(workspace: "ws_a", ticket: "t_1"), ConversationInputs(messages: [], tickets: tickets))
        XCTAssertEqual(items.map(\.text), ["Line 1", "Line 2", "Line 3"], "each chat line once, the older one kept")
        XCTAssertFalse(tickets[0].view!.historyTail.contains(worked), "only chat lines are kept, not old history")
    }

    func testTicketChatShowsChatLinesWithNamesOnce() {
        let view = TicketSnapshot(historyTail: [
            .init(at: "2026-11-21T09:00:00Z", by: "Claude", role: "agent", text: "Finished a task: Draft"),                       // not a chat line
            .init(at: "2026-11-21T09:01:00Z", by: "you", role: "person", text: "Keep the old colours", chat: true, messageId: "m_aaaaaaaaaaaaaaa1", name: "Nina Weber"),
            .init(at: "2026-11-21T09:02:00Z", by: "Claude", role: "agent", text: "Will do", chat: true, messageId: "m_aaaaaaaaaaaaaaa2"),
            .init(at: "2026-11-21T09:03:00Z", by: "you", role: "person", text: "Thanks", chat: true, messageId: "m_aaaaaaaaaaaaaaa3"),
            .init(at: "2026-11-21T09:04:00Z", by: "Claude", role: "agent", text: "Here is the draft", chat: true, messageId: "m_aaaaaaaaaaaaaaa4"),
        ])
        // The helper's last answer also came as a relay message with the same id: shown once.
        let relayCopy = PhoneMessage(message: TextMessage(id: "m_aaaaaaaaaaaaaaa4", from: "ws_a", to: "ph_1", type: "text", createdAt: "2026-11-21T09:04:00Z",
                                                          ticket: "t_1", body: TextBody(text: "Here is the draft", update: TextUpdate(kind: "result"))), workspaceName: "Marketing")
        let items = ConversationBuilder.items(.topic(workspace: "ws_a", ticket: "t_1"), ConversationInputs(messages: [relayCopy], tickets: [ticket("t_1", view: view)]))
        XCTAssertEqual(items.map(\.text), ["Keep the old colours", "Will do", "Thanks", "Here is the draft"])
        XCTAssertEqual(items[0].side, .them, "a typed name is someone writing on the computer")
        XCTAssertEqual(items[0].sender, "Nina Weber"); XCTAssertTrue(items[0].typedName)
        XCTAssertEqual(items[1].sender, "Claude"); XCTAssertFalse(items[1].typedName)
        XCTAssertEqual(items[2].side, .me, "you on the computer without a typed name is you")
        XCTAssertNil(items[3].sender, "the relay copy wins: the workspace's helper")
        XCTAssertEqual(ChatNames.caption(items[0], workspaceName: "Marketing"), "Nina Weber · not signed in")
        XCTAssertEqual(ChatNames.caption(items[1], workspaceName: "Marketing"), "Claude · Marketing")
        XCTAssertEqual(ChatNames.caption(items[3], workspaceName: "Marketing"), "Marketing")
    }

    func testSameTextWithOwnIdIsStillShownAndOldLinesCannotBeAnswered() {
        let view = TicketSnapshot(historyTail: [
            .init(at: "2026-11-21T09:01:00Z", by: "you", role: "person", text: "Thanks", chat: true, messageId: "m_bbbbbbbbbbbbbbb1"),
            .init(at: "2026-11-21T09:02:00Z", by: "Claude", role: "agent", text: "Old line", chat: true),
        ])
        let phoneThanks = PhoneMessage(message: TextMessage(id: "m_bbbbbbbbbbbbbbb0", from: "ph_1", to: "ws_a", type: "text", createdAt: "2026-11-21T09:00:00Z",
                                                            ticket: "t_1", body: TextBody(text: "Thanks")), workspaceName: "Marketing")
        let items = ConversationBuilder.items(.topic(workspace: "ws_a", ticket: "t_1"), ConversationInputs(messages: [phoneThanks], tickets: [ticket("t_1", view: view)]))
        XCTAssertEqual(items.map(\.text), ["Thanks", "Thanks", "Old line"], "a second Thanks with its own id is a second message")
        XCTAssertFalse(ChatNames.isLocalId(items[1].id))
        XCTAssertTrue(ChatNames.isLocalId(items[2].id), "an old line without an id gets a phone-only id and no Reply")
    }

    func testGeneralNeverShowsTicketChatLines() {
        let view = TicketSnapshot(historyTail: [.init(at: "2026-11-21T09:02:00Z", by: "Claude", role: "agent", text: "Will do", chat: true)])
        let items = ConversationBuilder.items(.general(workspace: "ws_a"), ConversationInputs(tickets: [ticket("t_1", view: view)]))
        XCTAssertTrue(items.isEmpty)
    }

    func testCaptionOnlyOnTheFirstBubbleOfARun() {
        func them(_ id: String, _ sender: String?) -> ConvItem { var i = ConvItem(id: id, at: "2026-11-21T09:0\(id)Z", side: .them, text: id); i.sender = sender; return i }
        let me = ConvItem(id: "3", at: "2026-11-21T09:03Z", side: .me, text: "me")
        let items = [them("1", "Claude"), them("2", "Claude"), me, them("4", "Claude"), them("5", nil)]
        XCTAssertEqual(items.indices.map { ChatNames.showsCaption(at: $0, in: items) }, [true, false, false, true, true])
    }

    // MARK: Ticket chats list

    private func topic(_ t: String, _ status: TopicStatus, at: String, unread: Int = 0, starting: Bool = false) -> TopicSummary {
        TopicSummary(id: starting ? .starting(workspace: "ws_a", id: t) : .topic(workspace: "ws_a", ticket: t), title: t, key: "MKT-1", status: status,
                     lastLine: "Claude: on it", lastAt: at, unread: unread, isStarting: starting, ticket: nil)
    }
    private func summary(_ id: String, _ topics: [TopicSummary]) -> WorkspaceSummary {
        WorkspaceSummary(workspace: Workspace(id: id, name: id == "ws_a" ? "Marketing" : "Product", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0),
                         presence: .unknown, general: ConversationSummary(id: .general(workspace: id), lastLine: "", lastAt: nil, unread: 0),
                         topics: topics, openQuestions: 0)
    }

    func testTicketChatsListNewestFirstAcrossWorkspaces() {
        let a = summary("ws_a", [topic("t_old", .working, at: "2026-11-20T09:00:00Z"), topic("t_new", .waitingOnYou, at: "2026-11-21T10:00:00Z", unread: 2)])
        let b = summary("ws_b", [topic("t_mid", .review, at: "2026-11-21T08:00:00Z")])
        let rows = TicketChatsRules.rows([a, b]).open
        XCTAssertEqual(rows.map { $0.topic.title }, ["t_new", "t_mid", "t_old"])
        XCTAssertEqual(rows[1].workspace.id, "ws_b")
        XCTAssertEqual(rows[1].accessibilityId, "ticket-ws_b|t_mid", "the id topic rows had on the workspace screen")
        XCTAssertEqual(TicketChatsRules.detail(rows[1], workspaceName: "Product"), "MKT-1 · Product")
    }

    func testFinishedTicketsGoUnderDoneAndStartingTopicsStay() {
        let a = summary("ws_a", [topic("c1", .working, at: "2026-11-21T10:00:00Z", starting: true),
                                 topic("t_done", .done, at: "2026-11-21T09:00:00Z"),
                                 topic("t_failed", .didntWork, at: "2026-11-21T08:30:00Z", unread: 1),
                                 topic("t_open", .backlog, at: "2026-11-21T07:00:00Z")])
        let rows = TicketChatsRules.rows([a])
        XCTAssertEqual(rows.open.map { $0.topic.title }, ["c1", "t_open"], "a topic that is still starting shows, so New topic is seen")
        XCTAssertEqual(rows.done.map { $0.topic.title }, ["t_done", "t_failed"])
    }

    func testTicketChatsLeaveOutWhatTheWorkspaceHides() {
        let a = summary("ws_a", [topic("t_shown", .working, at: "2026-11-21T10:00:00Z"), topic("t_archived", .working, at: "2026-11-21T09:00:00Z")])
        let rows = TicketChatsRules.rows([a], topics: { $0.topics.filter { $0.title != "t_archived" } })
        XCTAssertEqual(rows.open.map { $0.topic.title }, ["t_shown"], "archived chats stay in Archived")
    }

    func testTicketChatsListFollowsTheFilter() {
        let a = summary("ws_a", [topic("t_unread", .working, at: "2026-11-21T10:00:00Z", unread: 1),
                                 topic("t_needs", .waitingOnYou, at: "2026-11-21T09:00:00Z"),
                                 topic("t_quiet", .working, at: "2026-11-21T08:00:00Z")])
        XCTAssertEqual(TicketChatsRules.rows([a], filter: "Unread").open.map { $0.topic.title }, ["t_unread"])
        XCTAssertEqual(TicketChatsRules.rows([a], filter: "Needs your OK").open.map { $0.topic.title }, ["t_needs"])
        XCTAssertEqual(TicketChatsRules.rows([a], filter: "All").open.count, 3)
    }
}
