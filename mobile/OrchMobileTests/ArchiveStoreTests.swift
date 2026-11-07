import XCTest
@testable import OrchMobile

final class ArchiveStoreTests: XCTestCase {
    private let ws = "ws_pilatus001"
    private let now = ISO8601DateFormatter().date(from: "2026-11-20T12:00:00Z")!
    private func topic(_ t: String, _ status: TopicStatus, at: String) -> TopicSummary {
        TopicSummary(id: .topic(workspace: ws, ticket: t), title: t, key: nil, status: status, lastLine: "", lastAt: at, unread: 0, isStarting: false, ticket: nil)
    }
    private func summary(_ topics: [TopicSummary], muted: Bool = false, generalAt: String? = nil) -> WorkspaceSummary {
        WorkspaceSummary(workspace: Workspace(id: ws, name: "Pilatus", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0, mutedUntil: muted ? "forever" : nil),
                         presence: .unknown, general: ConversationSummary(id: .general(workspace: ws), lastLine: "", lastAt: generalAt, unread: 0),
                         topics: topics, openQuestions: 0)
    }
    private func key(_ t: String) -> String { ReadState.key(.topic(workspace: ws, ticket: t)) }

    func testManualArchiveHidesUntilANewMessage() {
        var a = ArchiveStore()
        a.archive(key("t1"), lastAt: "2026-11-10T10:00:00Z")
        XCTAssertTrue(a.isArchived(key: key("t1"), status: .done, lastAt: "2026-11-10T10:00:00Z", muted: false, now: now))
        XCTAssertFalse(a.isArchived(key: key("t1"), status: .done, lastAt: "2026-11-10T10:05:00Z", muted: false, now: now), "a new message brings it back")
        XCTAssertTrue(a.isArchived(key: key("t1"), status: .done, lastAt: "2026-11-10T10:05:00Z", muted: true, now: now), "muted workspace: stays archived")
    }

    func testMoveBackKeepsTheChatOutOfAutoArchive() {
        var a = ArchiveStore(); a.autoDays = 7
        let at = "2026-11-01T10:00:00Z"
        XCTAssertTrue(a.isArchived(key: key("t1"), status: .done, lastAt: at, muted: false, now: now))
        a.moveBack(key("t1"), lastAt: at)
        XCTAssertFalse(a.isArchived(key: key("t1"), status: .done, lastAt: at, muted: false, now: now))
    }

    func testAutoArchiveRules() {
        var a = ArchiveStore()
        let old = "2026-11-01T10:00:00Z"      // 19 days
        XCTAssertFalse(a.isArchived(key: "k", status: .done, lastAt: old, muted: false, now: now), "off by default")
        a.autoDays = 14
        XCTAssertTrue(a.isArchived(key: "k", status: .done, lastAt: old, muted: false, now: now))
        XCTAssertFalse(a.isArchived(key: "k", status: .done, lastAt: "2026-11-10T10:00:00Z", muted: false, now: now), "only 10 days quiet")
        for s in [TopicStatus.working, .waitingOnYou, .stopped, .didntWork] {
            XCTAssertFalse(a.isArchived(key: "k", status: s, lastAt: old, muted: false, now: now), "\(s) never auto-archives")
        }
        XCTAssertFalse(a.isArchived(key: "g", status: nil, lastAt: old, muted: false, now: now), "General never auto-archives")
        a.autoDays = 30
        XCTAssertFalse(a.isArchived(key: "k", status: .done, lastAt: old, muted: false, now: now))
    }

    func testDeleteOfferedOnlyForFinishedChatsAndGeneral() {
        XCTAssertFalse(ArchiveStore.canDelete(.working)); XCTAssertFalse(ArchiveStore.canDelete(.waitingOnYou))
        XCTAssertTrue(ArchiveStore.canDelete(.done)); XCTAssertTrue(ArchiveStore.canDelete(.stopped)); XCTAssertTrue(ArchiveStore.canDelete(nil))
    }

    func testSplitGroupsArchivedAndHidesGeneral() {
        var a = ArchiveStore()
        let s = summary([topic("t1", .done, at: "2026-11-10T10:00:00Z"), topic("t2", .working, at: "2026-11-19T10:00:00Z")], generalAt: "2026-11-15T10:00:00Z")
        a.archive(key("t1"), lastAt: "2026-11-10T10:00:00Z")
        a.archive(ReadState.key(.general(workspace: ws)), lastAt: "2026-11-15T10:00:00Z")
        let r = a.split(s, now: now)
        XCTAssertEqual(r.topics.map(\.id.ticket), ["t2"])
        XCTAssertFalse(r.general)
        XCTAssertEqual(r.archived.map(\.title), ["General", "t1"])
        XCTAssertTrue(r.archived[0].isGeneral)
    }

    func testEraseHidesOldMessagesAndTheTopic() {
        let id = ConversationID.topic(workspace: ws, ticket: "t_q3sum1")
        var d = ConversationInputs(workspaces: [Workspace(id: ws, name: "Pilatus", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0)])
        let tk = Ticket(id: "\(ws)|t_q3sum1", workspace: ws, workspaceName: "Pilatus", ticket: "t_q3sum1", title: "Q3", text: "done", status: .done, kind: "result", at: "2026-11-05T11:20:00Z", question: nil)
        d.tickets = [tk]
        func msg(_ id: String, _ at: String) -> PhoneMessage {
            PhoneMessage(message: TextMessage(id: id, from: ws, to: "ph", type: "text", createdAt: at, ticket: "t_q3sum1", body: TextBody(text: id)), workspaceName: "Pilatus")
        }
        d.messages = [msg("m1", "2026-11-05T10:00:00Z"), msg("m2", "2026-11-05T11:00:00Z")]
        XCTAssertEqual(ConversationBuilder.items(id, d).count, 2)
        var a = ArchiveStore(); a.erase(ReadState.key(id), upTo: "2026-11-05T11:00:00Z"); d.erased = a.erased
        XCTAssertTrue(ConversationBuilder.items(id, d).isEmpty)
        XCTAssertTrue(ConversationBuilder.topics(workspace: ws, d, read: ReadState()).isEmpty, "a deleted Done chat leaves the list")
        d.messages.append(msg("m3", "2026-11-06T09:00:00Z"))
        XCTAssertEqual(ConversationBuilder.items(id, d).map(\.id), ["m3"], "a new message brings it back, empty before")
        XCTAssertEqual(ConversationBuilder.topics(workspace: ws, d, read: ReadState()).count, 1)
    }

    func testPersistence() {
        let defaults = UserDefaults(suiteName: "archive-test-\(UUID().uuidString)")!
        var a = ArchiveStore(); a.autoDays = 14; a.archive("k", lastAt: "x"); a.save(defaults)
        XCTAssertEqual(ArchiveStore.load(defaults), a)
    }
}
