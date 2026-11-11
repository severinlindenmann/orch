import XCTest
@testable import OrchMobile

/// #465: an agent's result is not the person's verdict.
final class DoneReviewTests: XCTestCase {
    private func update(_ id: String, view: TicketSnapshot) -> TicketUpdate {
        TicketUpdate(id: id, workspace: "ws", workspaceName: "Workspace", ticket: "t_donerev1", kind: "result",
            title: nil, text: "", replyTo: nil, at: "2026-11-11T10:00:00Z", ticketView: view)
    }

    func testResultWithReviewSnapshotIsReview() throws {
        let ticket = try XCTUnwrap(TicketBuilder.build(
            updates: [update("result", view: TicketSnapshot(title: "Done, verdict asked", status: "review"))],
            questions: [], answers: [:]).first)
        XCTAssertEqual(ticket.kind, "result")
        XCTAssertEqual(ticket.status, .review)
        XCTAssertEqual(ticket.stateLine, "Ready for review")
        XCTAssertEqual(TopicStatus(ticket).chip, "Ready for review")
    }

    func testLightReviewResultOverridesFullDoneSnapshot() throws {
        let full = TicketSnapshot(title: "Done, verdict asked", status: "done", summary: "Work completed",
            checklist: [.init(text: "Complete the work", done: true)], running: false)
        let ticket = try XCTUnwrap(TicketBuilder.build(updates: [update("done", view: full),
            update("review", view: TicketSnapshot(status: "review", light: true))], questions: [], answers: [:]).first)
        XCTAssertEqual(ticket.status, .review)
        XCTAssertEqual(ticket.kind, "result")
        XCTAssertEqual(ticket.view?.status, "review")
        XCTAssertEqual(ticket.view?.title, full.title)
        XCTAssertEqual(ticket.view?.summary, full.summary)
        XCTAssertEqual(ticket.view?.checklist, full.checklist)
        XCTAssertEqual(TopicStatus(ticket).chip, "Ready for review")
    }

    func testReviewResultOffersVerdictOnlyWithUnansweredQuestion() throws {
        let question = Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_verdict", from: "ws", to: "phones",
            type: "question", createdAt: "2026-11-11T10:00:00Z", ticket: "t_donerev1",
            body: QuestionBody(questionId: "review-1", title: "Done, verdict asked", text: "Is this done?",
                options: ["accept", "changes"], recommended: nil, review: true)), workspaceName: "Workspace")
        for questions in [[], [question]] {
            let ticket = try XCTUnwrap(TicketBuilder.build(
                updates: [update("result", view: TicketSnapshot(status: "review"))], questions: questions, answers: [:]).first)
            XCTAssertEqual(ticket.status, .review)
            XCTAssertEqual(ReviewRules.reviewQuestion(ticket: ticket, workspaceId: "ws", ticketId: "t_donerev1",
                questions: questions, answers: [:]), questions.first)
            XCTAssertNil(ReviewRules.reviewQuestion(ticket: ticket, workspaceId: "ws", ticketId: "t_donerev1",
                questions: questions, answers: [question.id: "accept"]))
        }
    }
}
