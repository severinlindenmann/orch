import XCTest
@testable import OrchMobile

final class ReviewTests: XCTestCase {
    private func question(_ id: String = "q", review: Bool? = true, options: [String] = ["accept", "changes"],
                          workspace: String = "ws", ticket: String = "t", at: String = "2026-11-09T10:00:00Z") -> Question {
        Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: workspace, to: "phones", type: "question",
            createdAt: at, ticket: ticket, body: QuestionBody(questionId: "review-1", title: "Fish", text: "Is this done?",
                options: options, recommended: nil, review: review)), workspaceName: "Workspace")
    }
    private func ticket(_ status: Ticket.Status = .review) -> Ticket {
        Ticket(id: "ws|t", workspace: "ws", workspaceName: "Workspace", ticket: "t", title: "Fish", text: "Ready",
               status: status, kind: "result", at: "2026-11-09T10:00:00Z", question: nil)
    }
    func testDecodeAndReviewShape() throws {
        let json = #"{"message":{"schema":"orch.msg/1","id":"q","from":"ws","to":"phones","type":"question","created_at":"2026-11-09T10:00:00Z","ticket":"t","body":{"question_id":"review-1","title":"Fish","text":"Is this done?","options":["accept","changes"],"review":true,"recommended":null}},"workspace_name":"Workspace"}"#
        let q = try JSONCoding.decoder.decode(Question.self, from: Data(json.utf8))
        XCTAssertTrue(q.isReview)
        XCTAssertEqual(q.message.body.review, true)
        XCTAssertTrue(question(options: ["changes", "accept"]).isReview)
        XCTAssertFalse(question(review: nil).isReview)
        XCTAssertFalse(question(review: false).isReview)
        for options in [["accept"], ["accept", "accept"], ["accept", "changes", "changes"], ["Accept", "changes"], ["yes", "no"]] {
            XCTAssertFalse(question(options: options).isReview)
        }
    }
    func testRuleRequiresCurrentReviewAndMatchingOpenQuestion() {
        let q = question()
        func pick(_ t: Ticket?, _ qs: [Question], _ answers: [String: String] = [:]) -> Question? {
            ReviewRules.reviewQuestion(ticket: t, workspaceId: "ws", ticketId: "t", questions: qs, answers: answers)
        }
        XCTAssertEqual(pick(ticket(), [q]), q)
        XCTAssertNil(pick(nil, [q]))
        for status in [Ticket.Status.needsYou, .working, .paused, .backlog, .done] { XCTAssertNil(pick(ticket(status), [q])) }
        XCTAssertNil(pick(ticket(), [q], [q.id: "accept"]))
        XCTAssertNil(pick(ticket(), [question(workspace: "other")]))
        XCTAssertNil(pick(ticket(), [question(ticket: "other")]))
        XCTAssertNil(pick(ticket(), [question(review: nil)]))
        XCTAssertNil(pick(ticket(), []))
        let newer = question("new", at: "2026-11-09T10:00:00.500Z")
        XCTAssertEqual(pick(ticket(), [newer, q]), newer)
        XCTAssertEqual(pick(ticket(), [newer, q], [newer.id: "accept"]), q)
    }
    func testReviewNeverBecomesQuestionCardOrNeedsYouTicket() {
        let q = question()
        var data = ConversationInputs(); data.questions = [q]
        XCTAssertTrue(ConversationBuilder.items(.topic(workspace: "ws", ticket: "t"), data).isEmpty)
        XCTAssertTrue(ConversationBuilder.items(.general(workspace: "ws"), data).isEmpty)
        XCTAssertTrue(TicketBuilder.build(updates: [], questions: [q], answers: [:]).isEmpty)
        var chat = ChatData(); chat.questions = [q]
        XCTAssertTrue(ChatBuilder.ticketItems("ws", "t", chat).isEmpty)
        XCTAssertFalse(chat.isOpen(q))
        XCTAssertTrue(chat.isOpen(question(review: nil)))
    }
    func testReservedChangeNotes() {
        for text in ["accept", "changes", " ACCEPT\n", "\tChAnGeS "] { XCTAssertTrue(ReviewRules.isReservedAnswer(text)) }
        for text in ["Please accept the new layout", "Change the heading", "changes please"] { XCTAssertFalse(ReviewRules.isReservedAnswer(text)) }
    }

    @MainActor
    func testOpenQuestionCountExcludesReview() async {
        let previous = UserDefaults.standard.object(forKey: "mockReview")
        UserDefaults.standard.set(true, forKey: "mockReview")
        defer { UserDefaults.standard.set(previous, forKey: "mockReview") }
        Keychain.delete()
        defer { Keychain.delete() }
        let model = AppModel(useMock: true, voiceMode: .scripted)
        model.openSampleInvite()
        await model.connect(phoneName: "Review test")
        await model.finishSetup(allowNotifications: false)
        await model.refresh()
        XCTAssertTrue(model.questions.contains(where: \.isReview))
        XCTAssertEqual(model.openQuestionCount, model.questions.filter { !$0.isReview }.count)
        XCTAssertEqual(model.ticket(MockRelay.pilatus, MockRelay.reviewTicketId)?.status, .review)
    }
}
