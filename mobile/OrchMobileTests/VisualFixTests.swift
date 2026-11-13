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
        XCTAssertEqual(InfoGroup.links.tabLabel(count: 4), "Links (4)")
        XCTAssertEqual(InfoGroup.artifacts.tabLabel(count: 1), "Previews (1)", "not Results: that is the section above")
        for group in InfoGroup.allCases { XCTAssertEqual(group.tabLabel(count: 0), group.title) }
    }

    func testSharedFiltersOnlyWithContentAndProgressRow() {
        let shown = InfoGroup.visible(counts: [.photos: 0, .files: 2, .links: 1, .artifacts: 0])
        XCTAssertEqual(shown, [.files, .links])
        XCTAssertEqual(InfoGroup.current(.photos, visible: shown), .files, "an empty filter falls back to the first with content")
        XCTAssertEqual(InfoGroup.current(.links, visible: shown), .links)
        XCTAssertNil(InfoGroup.current(.photos, visible: []), "nothing shared: no Shared list at all")
        XCTAssertTrue(InfoGroup.showsTabs(shown))
        XCTAssertFalse(InfoGroup.showsTabs([.files]), "a lone filter shows no tab row")
        XCTAssertEqual(InfoGroup.progressText(done: 3, total: 4), "3 of 4 done")
        XCTAssertNil(InfoGroup.progressText(done: 0, total: 0))
    }

    func testVoiceLoadOnlyFailsForARealFailure() {
        XCTAssertEqual(VoiceLoadResult.from(blobId: nil, data: nil, loaded: false), .noSource, "still uploading: waits, not broken")
        XCTAssertEqual(VoiceLoadResult.from(blobId: "", data: nil, loaded: false), .noSource)
        XCTAssertEqual(VoiceLoadResult.from(blobId: "b1", data: nil, loaded: false), .failed, "blob fetch failed")
        XCTAssertEqual(VoiceLoadResult.from(blobId: "b1", data: Data([1]), loaded: false), .failed, "audio could not be decoded")
        XCTAssertEqual(VoiceLoadResult.from(blobId: "b1", data: Data([1]), loaded: true), .loaded)
    }

    func testResultSubtitleHasNoHashAndVoiceTimeCountsDown() {
        let pdf = ArtifactItem(id: "a", title: "Offer", kind: .pdf, rev: "2f7f62e9abc")
        XCTAssertEqual(pdf.subtitle(pages: 3), "PDF · 3 pages")
        XCTAssertFalse(pdf.subtitle.contains("2f7f62e"))
        XCTAssertEqual(pdf.versionDetail, "Version 2f7f62e")
        XCTAssertEqual(voiceTimeLabel(duration: 7, progress: 0, started: false), clockText(7))
        XCTAssertEqual(voiceTimeLabel(duration: 10, progress: 0.5, started: true), clockText(5))
        XCTAssertNil(voiceTimeLabel(duration: 0, progress: 0, started: false))
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

    /// 12 Nov phone UX batch 1: pinned cap, one-line titles, one filter rule, one Chat-card line, no status avatar colours.
    func testChatsListPhoneUXRules() {
        let qs = (0..<5).map { question("q\($0)", from: "w\($0)", ticket: nil, at: "2026-11-12T0\($0):00:00Z") }
        XCTAssertEqual(ChatsRowRules.pinned(qs).map(\.id), ["q0", "q1", "q2"])
        XCTAssertEqual(ChatsRowRules.pinned(Array(qs.prefix(2))).count, 2)
        XCTAssertEqual(ChatsRowRules.titleLines(false), 1)
        XCTAssertEqual(ChatsRowRules.titleLines(true), 2)
        XCTAssertTrue(ChatsRowRules.matches("All", unread: 0, needsYou: false))
        XCTAssertTrue(ChatsRowRules.matches("Unread", unread: 2, needsYou: false))
        XCTAssertFalse(ChatsRowRules.matches("Unread", unread: 0, needsYou: true))
        XCTAssertTrue(ChatsRowRules.matches("Needs your OK", unread: 0, needsYou: true))
        XCTAssertFalse(ChatsRowRules.matches("Needs your OK", unread: 3, needsYou: false))
        XCTAssertEqual(ChatsRowRules.preview("Hi", working: true), "Working…")
        XCTAssertEqual(ChatsRowRules.preview("Hi", starting: true, working: true), "Getting started…")
        XCTAssertEqual(WorkspaceView.helperLine(name: "Finance", anyWorking: true, lastLine: "Hi"), "Finance is working…")
        XCTAssertEqual(WorkspaceView.helperLine(name: "Finance", anyWorking: false, lastLine: " Hi "), "Hi")
        XCTAssertEqual(WorkspaceView.helperLine(name: "Finance", anyWorking: false, lastLine: ""), "Talk to Finance")
        XCTAssertEqual(ChatsRowRules.preview("New reply", working: true, unread: 1), "New reply")
        XCTAssertEqual(WorkspaceView.helperLine(name: "Finance", anyWorking: true, lastLine: "New reply", unread: 2), "New reply")
        XCTAssertEqual(WorkspaceView.activeOrder, [.waitingOnYou, .review, .working, .paused, .backlog])
        for token in LookData.colors.map(\.id) {
            XCTAssertFalse(["amber", "teal", "green", "lime"].contains(WorkspaceBadge.identityColor(token)), token)
        }
        XCTAssertEqual(WorkspaceBadge.identityColor("pink"), "pink")
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
