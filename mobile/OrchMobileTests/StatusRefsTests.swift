import XCTest
@testable import OrchMobile

/// W5-S: the new ticket statuses (PLAN-A section 5) and References (section 4).
final class StatusRefsTests: XCTestCase {
    // MARK: status words

    func testTicketStatusWordsMapToPhoneGroups() {
        typealias S = Ticket.Status
        XCTAssertEqual(S(ticketStatus: "open"), .backlog); XCTAssertEqual(S(ticketStatus: "ready"), .backlog)
        XCTAssertEqual(S(ticketStatus: "active"), .working); XCTAssertEqual(S(ticketStatus: "waiting"), .needsYou)
        XCTAssertEqual(S(ticketStatus: "review"), .review)
        XCTAssertEqual(S(ticketStatus: "done"), .done); XCTAssertEqual(S(ticketStatus: "dropped"), .done)
        XCTAssertNil(S(ticketStatus: "doing")); XCTAssertNil(S(ticketStatus: "working")); XCTAssertNil(S(ticketStatus: nil))
    }

    private func note(_ status: String?, kind: String = "note", t: String = "t_1") -> TicketUpdate {
        TicketUpdate(id: "m_" + t + (status ?? "none"), workspace: "ws_a", workspaceName: "A", ticket: t, kind: kind, title: "T", text: "x", replyTo: nil,
                     at: "2026-11-07T10:00:00Z", ticketView: TicketSnapshot(title: "T", status: status))
    }

    func testTopicStatusFollowsTheTicketStatus() {
        func topic(_ s: String?, kind: String = "note") -> TopicStatus { TopicStatus(TicketBuilder.build(updates: [note(s, kind: kind)], questions: [], answers: [:])[0]) }
        XCTAssertEqual(topic("open"), .backlog); XCTAssertEqual(topic("ready"), .backlog)
        XCTAssertEqual(topic("active"), .working); XCTAssertEqual(topic("waiting"), .waitingOnYou)
        XCTAssertEqual(topic("review"), .review); XCTAssertEqual(topic("done"), .done)
        XCTAssertEqual(topic("dropped"), .dropped, "dropped is not shown as plain Done")
        XCTAssertEqual(topic(nil), .working, "an old snapshot without a status keeps working")
        XCTAssertEqual(topic("review", kind: "result"), .review, "an agent's done lands as review")
        XCTAssertEqual(topic(nil, kind: "result"), .done)
        XCTAssertEqual(topic("active", kind: "failure"), .working, "the stored status wins over the update kind")
        XCTAssertEqual(topic("done", kind: "failure"), .didntWork, "a finished ticket keeps its failure sign")
        XCTAssertEqual(topic(nil, kind: "failure"), .didntWork, "old snapshot: the kind decides")
        // E2: a result update on a ticket that is still open must not list it under Done
        XCTAssertEqual(topic("open", kind: "result"), .backlog); XCTAssertEqual(topic("active", kind: "result"), .working)
        XCTAssertEqual(topic("waiting", kind: "result"), .waitingOnYou)
    }

    func testChipWordsAndLabels() {
        XCTAssertEqual(TopicStatus.working.chip, "Claude is working"); XCTAssertEqual(TopicStatus.waitingOnYou.chip, "Needs you")
        XCTAssertEqual(TopicStatus.review.chip, "Ready for review"); XCTAssertEqual(TopicStatus.done.chip, "Done")
        XCTAssertEqual(TopicStatus.allCases.map(\.label), ["Working", "Needs you", "Ready for review", "Paused", "Not started", "Done", "Dropped", "Stopped", "Didn't work"])
    }

    func testGroupingOrderOfTicketsIsNeedsYouReviewWorkingBacklogDone() {
        let ups = [note("done", t: "t_5"), note("open", t: "t_4"), note("active", t: "t_3"), note("review", t: "t_2"), note("waiting", t: "t_1")]
        let t = TicketBuilder.build(updates: ups, questions: [], answers: [:])
        XCTAssertEqual(t.map(\.status), [.needsYou, .review, .working, .backlog, .done])
    }

    func testOnlyDoneAutoArchivesAndDeleteNeedsAFinishedChat() {
        var a = ArchiveStore(); a.autoDays = 3
        let old = "2020-01-01T10:00:00Z"
        for s in TopicStatus.allCases {
            XCTAssertEqual(a.isArchived(key: "k", status: s, lastAt: old, muted: false), s == .done, "\(s)")
        }
        XCTAssertFalse(a.isArchived(key: "g", status: nil, lastAt: old, muted: false))
        for s in [TopicStatus.working, .waitingOnYou, .review, .backlog] { XCTAssertFalse(ArchiveStore.canDelete(s), "\(s)") }
        for s in [TopicStatus.done, .stopped, .didntWork] { XCTAssertTrue(ArchiveStore.canDelete(s), "\(s)") }
        XCTAssertTrue(ArchiveStore.canDelete(nil))
    }

    // MARK: references

    /// contracts/examples/ticket/valid-refs.json (refs) plus an unknown kind and a broken item.
    private let refsJSON = #"""
    {"title":"T","status":"review","refs":[
      {"kind":"url","url":"https://example.com","at":"2026-11-07T10:00:00Z","by":"human:tester"},
      {"kind":"ticket","ticket":"t_9d2x1q","at":"2026-11-07T10:00:00Z"},
      {"kind":"artifact","ticket":"t_9d2x1q","name":"report.pdf"},
      {"kind":"file","path":"docs/spec.md","line":40},
      {"kind":"github:pr","url":"https://github.com/acme/app/pull/1","title":"Add CSV export","status":"merged"},
      {"kind":"hologram","url":"https://x.example"},
      {"kind":"ticket"},
      {"nokind":true},
      42
    ]}
    """#

    func testRefsDecodeAndSkipUnknownKinds() throws {
        let v = try JSONDecoder().decode(TicketSnapshot.self, from: Data(refsJSON.utf8))
        XCTAssertEqual(v.status, "review")
        XCTAssertEqual(v.refs.compactMap(\.kind), [.url, .ticket, .artifact, .file, .url])
        XCTAssertEqual(v.refs[3].pathText, "docs/spec.md:40")
        XCTAssertEqual(v.refs[4].title, "Add CSV export")
    }

    func testOldSnapshotsStillDecode() throws {
        let old = #"{"title":"T","status":"working","checklist":[{"text":"a","done":true}],"attachments":[{"kind":"link","title":"x","url":"https://a.example"}]}"#
        let v = try JSONDecoder().decode(TicketSnapshot.self, from: Data(old.utf8))
        XCTAssertEqual(v.refs, []); XCTAssertEqual(Ticket.Status(ticketStatus: v.status), nil, "working is not a ticket status word")
        let bad = #"{"title":"T","refs":"nope"}"#
        XCTAssertEqual(try JSONDecoder().decode(TicketSnapshot.self, from: Data(bad.utf8)).refs, [])
    }

    func testRefRowsAreSafeAndResolved() throws {
        var v = try JSONDecoder().decode(TicketSnapshot.self, from: Data(refsJSON.utf8))
        v.refs.append(TicketRef(rawKind: "url", url: "javascript:alert(1)"))
        v.refs.append(TicketRef(rawKind: "url", url: "file:///etc/passwd"))
        let item = ArtifactItem(.init(kind: "file", title: "report.pdf", blobId: "b_1", name: "report.pdf", size: 3), in: .topic(workspace: "ws_a", ticket: "t_9d2x1q"))
        let rows = RefRow.rows(v.refs, lookup: { $0 == "t_9d2x1q" ? ("PIL-12", "Q3 summary") : nil },
                               attachments: { t, n in t == "t_9d2x1q" && n == "report.pdf" ? item : nil })
        XCTAssertEqual(rows.count, 5, "unsafe addresses are dropped")
        guard case .link(_, let title, let host, let url) = rows[0] else { return XCTFail("link") }
        XCTAssertEqual(title, "example.com"); XCTAssertEqual(host, "example.com"); XCTAssertEqual(url.scheme, "https")
        XCTAssertEqual(rows[1], .ticket(id: "ref1", label: "PIL-12 · Q3 summary", known: true))
        guard case .artifact(_, let name, let found) = rows[2] else { return XCTFail("artifact") }
        XCTAssertEqual(name, "report.pdf"); XCTAssertEqual(found?.blobId, "b_1")
        XCTAssertEqual(rows[3], .file(id: "ref3", text: "docs/spec.md:40"))
        guard case .link(_, let prTitle, _, _) = rows[4] else { return XCTFail("add-on link") }
        XCTAssertEqual(prTitle, "Add CSV export")
        let unknown = RefRow.rows([TicketRef(rawKind: "ticket", ticket: "t_zzzzzz")], lookup: { _ in nil }, attachments: { _, _ in nil })
        XCTAssertEqual(unknown, [.ticket(id: "ref0", label: "Another topic", known: false)])
    }
}
