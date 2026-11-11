import XCTest
@testable import OrchMobile

final class TicketRulesTests: XCTestCase {
    private func q(_ id: String, answer: String? = nil) -> ConvItem {
        var i = ConvItem(id: id, at: "2026-11-06T10:00:00Z", side: .them, kind: .question); i.answer = answer; return i
    }

    func testNeedsYouWords() {
        XCTAssertEqual(ConversationRules.needsYouText(position: 1, of: 1), "Needs your OK")
        XCTAssertEqual(ConversationRules.needsYouText(position: 2, of: 3), "Needs your OK · 2 of 3")
    }

    func testOpenPositionCountsOnlyOpenQuestions() {
        let items = [q("a", answer: "Yes"), q("b"), q("c")]
        XCTAssertEqual(ConversationRules.openPosition(of: "b", in: items)?.n, 1)
        XCTAssertEqual(ConversationRules.openPosition(of: "c", in: items)?.n, 2)
        XCTAssertEqual(ConversationRules.openPosition(of: "c", in: items)?.of, 2)
        XCTAssertNil(ConversationRules.openPosition(of: "a", in: items), "answered is not open")
        XCTAssertNil(ConversationRules.openPosition(of: "zzz", in: items))
        var result = ConvItem(id: "r", at: "2026-11-06T11:00:00Z", side: .them); result.label = "RESULT"
        XCTAssertNil(ConversationRules.openPosition(of: "b", in: items + [result]), "stale is not open")
    }

    func testAnsweredText() {
        XCTAssertNil(ConversationRules.answeredText(in: []))
        XCTAssertEqual(ConversationRules.answeredText(in: [q("a"), q("b", answer: "No")]), "1 of 2 answered")
    }

    func testStatusWordsAreTheDashboardWords() {
        XCTAssertEqual(TopicStatus.waitingOnYou.label, "Needs your OK")
        XCTAssertEqual(TopicStatus.working.label, "Working")
        XCTAssertEqual(TopicStatus.paused.label, "Paused")
        XCTAssertEqual(TopicStatus.review.label, "Ready for review")
        XCTAssertEqual(TopicStatus.backlog.label, "Not started")
        XCTAssertEqual(TopicStatus.done.label, "Done")
        XCTAssertEqual(TopicStatus.dropped.label, "Dropped")
    }

    private let files = [
        TicketSnapshot.Attachment(kind: "file", title: "Shortlist", blobId: "b1", name: "shortlist.md", artifactId: "a_1"),
        TicketSnapshot.Attachment(kind: "file", title: nil, blobId: "b2", name: "artifacts/menu.pdf", artifactId: "a_2"),
        TicketSnapshot.Attachment(kind: "link", title: "docs.example.com", url: "https://docs.example.com/x"),
    ]

    func testMatcherFindsPathAndFileNames() {
        let text = "Please check `artifacts/shortlist.md`, then menu.pdf. Is that ok?"
        let found = ArtifactMentions.mentions(in: text, attachments: files)
        XCTAssertEqual(found.map(\.attachmentId), ["a_1", "a_2"])
        XCTAssertEqual(String(text[found[0].range]), "artifacts/shortlist.md")
        XCTAssertEqual(String(text[found[1].range]), "menu.pdf")
    }

    func testMatcherLeavesOtherTextPlain() {
        XCTAssertTrue(ArtifactMentions.mentions(in: "Use other.md or nothing at all", attachments: files).isEmpty, "no attachment of that name")
        XCTAssertTrue(ArtifactMentions.mentions(in: "Which layout? shortlist", attachments: files).isEmpty, "no dot, not a file name")
        XCTAssertTrue(ArtifactMentions.mentions(in: "see docs.example.com", attachments: files).isEmpty, "links never match")
        XCTAssertTrue(ArtifactMentions.mentions(in: "see shortlist.md", attachments: []).isEmpty)
        XCTAssertEqual(ArtifactMentions.mentions(in: "SHORTLIST.MD", attachments: files).count, 1, "case does not matter")
    }

    func testOfflineWording() {
        XCTAssertEqual(QueuedNote.waiting, "Waiting · will send when online")
        XCTAssertNil(QueuedNote.text(for: nil))
        var o = OutboxItem(clientId: "c", phone: "p", kind: .send, workspace: "w", createdAt: "2026-11-06T10:00:00Z")
        XCTAssertEqual(QueuedNote.text(for: o), "Waiting · will send when online")
        o.throttleCount = 1
        XCTAssertEqual(QueuedNote.text(for: o), "Try again later")
        o.sentMessageId = "m1"
        XCTAssertNil(QueuedNote.text(for: o), "sent: no note")
        o.sentMessageId = nil; o.failure = "no"
        XCTAssertNil(QueuedNote.text(for: o), "failed shows Not sent, not a wait note")
    }
}
