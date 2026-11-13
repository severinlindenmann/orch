import XCTest
@testable import OrchMobile

@MainActor
final class VisualFixTests: XCTestCase {
    func testChatTimeFormat() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(secondsFromGMT: 0))
        let now = try XCTUnwrap(ShellTime.date("2026-11-11T16:00:00Z"))
        XCTAssertEqual(ShellTime.short("2026-11-11T14:02:00Z", now: now, calendar: calendar), "14:02")
        XCTAssertEqual(ShellTime.short("2026-10-31T14:02:00Z", now: now, calendar: calendar), "31 Oct")
        XCTAssertEqual(ShellTime.short("2026-11-10T14:02:00Z", now: now, calendar: calendar), "Yesterday")
        XCTAssertEqual(ShellTime.short(nil, now: now, calendar: calendar), "")
    }

    func testTasksWording() {
        XCTAssertEqual(ConversationRules.summaryText(done: 3, total: 3, status: "Ready for review"), "3 of 3 steps done")
        XCTAssertEqual(ConversationRules.summaryText(done: 1, total: 3, status: "Working"), "1 of 3 steps done")
        XCTAssertEqual(ConversationRules.summaryText(done: 0, total: 0, status: "Working"), "")
    }

    func testTabCountsKeepReferencePrefixAndOmitZero() {
        XCTAssertEqual(InfoGroup.photos.tabLabel(count: 1), "Photos (1)")
        XCTAssertEqual(InfoGroup.files.tabLabel(count: 1), "Files (1)")
        XCTAssertEqual(InfoGroup.links.tabLabel(count: 4), "References (4)")
        XCTAssertEqual(InfoGroup.artifacts.tabLabel(count: 1), "Artifacts (1)")
        for group in InfoGroup.allCases { XCTAssertEqual(group.tabLabel(count: 0), group.title) }
    }

    func testChatRowPreview() {
        XCTAssertEqual(ChatsRowRules.preview(""), "No messages yet")
        XCTAssertEqual(ChatsRowRules.preview(" \n "), "No messages yet")
        XCTAssertEqual(ChatsRowRules.preview("Allow access?"), "Allow access?")
        XCTAssertEqual(ChatsRowRules.preview("", starting: true), "Getting started…")
        XCTAssertEqual(ChatsRowRules.preview("Report ready"), "Report ready")
    }

    private func question(_ id: String, from ws: String, ticket: String?, at: String, review: Bool = false) -> Question {
        Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: ws, to: "phones", type: "question",
            createdAt: at, ticket: ticket, body: QuestionBody(questionId: id, title: nil, text: "OK?",
                options: review ? ["accept", "changes"] : ["Yes", "No"], recommended: nil, review: review ? true : nil)), workspaceName: ws)
    }

    func testChatListCountsHaveOneMeaningEach() {
        let qs = [question("a", from: "w1", ticket: "t1", at: "2026-11-12T10:00:00Z"),
                  question("b", from: "w1", ticket: "t1", at: "2026-11-12T09:00:00Z"),
                  question("c", from: "w1", ticket: nil, at: "2026-11-12T11:00:00Z"),
                  question("d", from: "w2", ticket: "t1", at: "2026-11-12T12:00:00Z"),
                  question("e", from: "w2", ticket: nil, at: "2026-11-12T08:00:00Z"),
                  question("r", from: "w2", ticket: nil, at: "2026-11-12T08:00:00Z", review: true)]
        let answers = ["e": "Yes"]
        // Row label: open questions only (answered and review questions don't count).
        XCTAssertEqual(ChatsRowRules.openQuestions(qs, answers: answers, workspace: "w1").count, 3)
        XCTAssertEqual(ChatsRowRules.openQuestions(qs, answers: answers, workspace: "w2").count, 1)
        // "Needs your OK · N": one per conversation, and N is the number of rows listed.
        let needsYou = ChatsRowRules.needsYou(qs, answers: answers)
        XCTAssertEqual(needsYou.map(\.id), ["b", "c", "d"])
        XCTAssertEqual(ChatsRowRules.needsYou([], answers: [:]).count, 0)
        XCTAssertNil(ChatsRowRules.questionLabel(0))
        XCTAssertEqual(ChatsRowRules.questionLabel(1), "1 question")
        XCTAssertEqual(ChatsRowRules.questionLabel(3), "3 questions")
        // The preview stays the last message; questions get their own line.
        XCTAssertEqual(ChatsRowRules.preview("Allow access?"), "Allow access?")
    }

    func testWorkspaceStatusCombinesConnectionAndPresence() {
        var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "Europe/Zurich")!
        let now = ISO8601DateFormatter().date(from: "2026-11-12T14:00:00Z")!
        let fresh = Presence.of(lastSeen: "2026-11-12T13:58:00Z", now: now)
        let old = Presence.of(lastSeen: "2026-11-04T10:41:00Z", now: now)
        let today = Presence.of(lastSeen: "2026-11-12T12:02:00Z", now: now)
        XCTAssertEqual(WorkspaceStatus.of(connection: .ok, presence: fresh).text(now: now, calendar: cal), "Online")
        XCTAssertTrue(WorkspaceStatus.of(connection: .ok, presence: fresh).isOnline)
        XCTAssertEqual(WorkspaceStatus.of(connection: .checking, presence: fresh), .online)
        XCTAssertEqual(WorkspaceStatus.of(connection: .ok, presence: old).text(now: now, calendar: cal), "Computer not reachable, last seen 4 Nov")
        XCTAssertEqual(WorkspaceStatus.of(connection: .ok, presence: today).text(now: now, calendar: cal), "Computer not reachable, last seen 13:02")
        XCTAssertEqual(WorkspaceStatus.of(connection: .ok, presence: .unknown).text(now: now, calendar: cal), "Computer not reachable")
        XCTAssertFalse(WorkspaceStatus.of(connection: .ok, presence: old).isOnline)
        for p in [fresh, old, Presence.unknown] {
            let s = WorkspaceStatus.of(connection: .unreachable, presence: p)
            XCTAssertEqual(s.text(now: now, calendar: cal), "Offline, no connection"); XCTAssertFalse(s.isOnline)
        }
    }
}
