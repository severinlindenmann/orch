import XCTest
@testable import OrchMobile

final class MakeTicketTests: XCTestCase {
    private func question(proposal: String? = "make_ticket", options: [String] = ["make", "not_now"]) -> Question {
        let fixture = MockRelay.makeTicketQuestion
        var body = fixture.message.body
        body.proposal = proposal
        return Question(message: QuestionMessage(schema: "orch.msg/1", id: fixture.id, from: MockRelay.pilatus,
            to: "phones", type: "question", createdAt: fixture.message.createdAt, ticket: nil,
            body: QuestionBody(questionId: body.questionId, title: body.title, text: body.text, options: options,
                recommended: nil, proposal: body.proposal, when: body.when)), workspaceName: "Pilatus Workspace")
    }

    func testDecodeAndShape() throws {
        let json = #"{"message":{"schema":"orch.msg/1","id":"m_maketicket00001","from":"ws_pilatus001","to":"phones","type":"question","created_at":"2026-11-09T10:00:00Z","body":{"question_id":"proposal-m_maketicket00001","title":"Check the backups","text":"Here is a ticket for Friday 13 Nov.","options":["make","not_now"],"proposal":"make_ticket","recommended":null,"when":"2026-11-13"}},"workspace_name":"Pilatus Workspace"}"#
        let decoded = try JSONCoding.decoder.decode(Question.self, from: Data(json.utf8))
        XCTAssertTrue(decoded.isMakeTicket)
        XCTAssertEqual(decoded.message.body.proposal, "make_ticket")
        XCTAssertEqual(decoded.message.body.when, "2026-11-13")
        XCTAssertNil(decoded.message.ticket)
        XCTAssertTrue(question(options: ["not_now", "make"]).isMakeTicket)
        XCTAssertFalse(question(proposal: nil).isMakeTicket)
        XCTAssertFalse(question(proposal: "other").isMakeTicket)
        for options in [["make"], ["make", "make"], ["make", "not_now", "not_now"], ["make", "not now"], ["Make", "not_now"]] {
            XCTAssertFalse(question(options: options).isMakeTicket)
        }
    }

    func testContractVectors() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/vectors/proposal-question-v1.json"))
        let vector = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        for key in ["valid", "invalid"] {
            let shapes = try XCTUnwrap(vector[key] as? [[String: Any]])
            XCTAssertFalse(shapes.isEmpty)
            for shape in shapes {
                let message = try XCTUnwrap(shape["message"] as? [String: Any])
                let wrapped = try JSONSerialization.data(withJSONObject: ["message": message, "workspace_name": "Pilatus Workspace"])
                let decoded = try JSONCoding.decoder.decode(Question.self, from: wrapped)
                XCTAssertEqual(decoded.isMakeTicket, key == "valid", shape["name"] as? String ?? key)
            }
        }
    }

    func testGeneralPlacementAndNeedsYouExclusion() throws {
        let q = question()
        var data = ConversationInputs(); data.questions = [q]
        let items = ConversationBuilder.items(.general(workspace: MockRelay.pilatus), data)
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(ReadState().unread(ReadState.generalKey(MockRelay.pilatus), in: items), 0)
        XCTAssertTrue(try XCTUnwrap(items.first?.question).isMakeTicket)
        XCTAssertNil(ConversationRules.openPosition(of: q.id, in: items))
        XCTAssertNil(ConversationRules.answeredText(in: items))
        XCTAssertFalse(ConversationRules.showsWriteOwn(q))
        XCTAssertTrue(TicketBuilder.build(updates: [], questions: [q], answers: [:]).isEmpty)
        var chat = ChatData(); chat.questions = [q]
        XCTAssertFalse(chat.isOpen(q))
        data.answers[q.id] = "make"
        XCTAssertEqual(ConversationBuilder.items(.general(workspace: MockRelay.pilatus), data).first?.answer, "make")
    }

    @MainActor
    func testDateLabel() {
        XCTAssertEqual(MakeTicketCard.dateLabel("2026-11-13"), "Fri 13 Nov")
        XCTAssertNil(MakeTicketCard.dateLabel(nil))
        XCTAssertNil(MakeTicketCard.dateLabel("invalid"))
    }

    @MainActor
    func testOpenQuestionCountExcludesMakeTicket() async {
        let previous = UserDefaults.standard.object(forKey: "mockMakeTicket")
        UserDefaults.standard.set(true, forKey: "mockMakeTicket")
        defer { UserDefaults.standard.set(previous, forKey: "mockMakeTicket") }
        Keychain.delete()
        defer { Keychain.delete() }
        let model = AppModel(useMock: true, voiceMode: .scripted)
        model.openSampleInvite()
        await model.connect(phoneName: "Make ticket test")
        await model.finishSetup(allowNotifications: false)
        await model.refresh()
        XCTAssertTrue(model.questions.contains(where: \.isMakeTicket))
        XCTAssertEqual(model.openQuestionCount, model.questions.filter { !$0.isReview && !$0.isMakeTicket }.count)
        let q = MockRelay.makeTicketQuestion
        await model.answer(q, with: "make")
        XCTAssertEqual(model.answers[q.id], "make")
    }
}
