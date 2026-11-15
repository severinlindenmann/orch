import XCTest
@testable import OrchMobile

/// A card whose review_result is "changed" goes back to the front of the waiting list (P4b item 6).
@MainActor
final class ReviewChangedTests: XCTestCase {
    func testChangedResultPutsTheCardBackInFront() async throws {
        let d = UserDefaults.standard
        d.set(true, forKey: "mockReviewStack"); d.set("changed", forKey: "mockReviewResult")
        defer { d.removeObject(forKey: "mockReviewStack"); d.removeObject(forKey: "mockReviewResult") }
        let model = AppModel(useMock: true, voiceMode: .scripted)
        model.openSampleInvite(); await model.connect(phoneName: "T"); await model.finishSetup(allowNotifications: false)
        let q = MockReviewStack.questions[0]
        let item = try XCTUnwrap(ReviewStackRules.item(for: q))
        let v = try XCTUnwrap(ReviewStackRules.verdict(item, .ok))
        try await model.submitVerdict(item, v)
        await model.refresh()
        let pending = Set(model.outbox.items.compactMap { $0.verdict != nil ? $0.questionMessageId : nil })
        let changed = ReviewStackRules.changedIds(questions: Array(model.questionLog.values), messages: model.messages, pending: pending)
        XCTAssertTrue(pending.isEmpty, "the result closes the answer: \(pending)")
        XCTAssertEqual(changed, [q.id])
        let stack = ReviewStackRules.stack(questions: model.questions + model.questionLog.values.filter { changed.contains($0.id) }, answers: model.answers, pending: pending, changed: changed)
        XCTAssertEqual(stack.first?.id, q.id)
        XCTAssertEqual(ReviewStateText.text(.changed), "This changed. Look again.")
    }

    func testAnOlderResultDoesNotCloseAFreshAnswer() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("rc" + UUID().uuidString.prefix(6))
        defer { try? FileManager.default.removeItem(at: dir) }
        let box = Outbox(directory: dir, phone: "ph_iphone0001")
        let q = MockReviewStack.questions[0]
        let v = ReviewVerdict(verdict: .ok, digest: q.message.body.digest!)
        var item = try box.enqueueAnswer(question: q, answer: "Send it", verdict: v)
        let old = PhoneMessage(message: TextMessage(id: "m_old", from: q.message.from, to: "ph_iphone0001", type: "text", createdAt: "2020-01-01T00:00:00Z", ticket: nil,
                                                    body: TextBody(text: "x", reviewResult: ReviewResult(result: "changed")), replyTo: q.id), workspaceName: "P")
        item = box.items[0]
        box.reconcile(with: [old])
        XCTAssertEqual(box.items.count, 1, "an older result must not close it")
    }
}
