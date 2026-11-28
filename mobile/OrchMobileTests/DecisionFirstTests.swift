import XCTest
@testable import OrchMobile

/// ORCH-2187 (Focused review F): the phone's Review card leads with "You decide", "If you wait" and "What matters" when the
/// sending workspace has its decision-first switch on (relay-api.md "Questions"), and stays as before otherwise.
final class DecisionFirstTests: XCTestCase {
    private func body(_ json: String) throws -> QuestionBody { try JSONCoding.decoder.decode(QuestionBody.self, from: Data(json.utf8)) }
    private func item(_ b: QuestionBody, id: String = "m1") throws -> ReviewItem {
        let m = QuestionMessage(schema: "orch.msg/1", id: id, from: "ws_p", to: "phones", type: "question", createdAt: "2026-11-28T09:10:00Z", ticket: "t_1", body: b)
        return try XCTUnwrap(ReviewStackRules.item(for: Question(message: m, workspaceName: "P")))
    }

    /// Every case of contracts/vectors/question-decision-first-v1.json: what the phone shows for each valid message.
    func testContractVector() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let url = root.appendingPathComponent("contracts/vectors/question-decision-first-v1.json")
        let vector = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        let valid = try XCTUnwrap(vector["valid"] as? [[String: Any]])
        XCTAssertEqual(valid.count, 4)
        for v in valid {
            let name = v["name"] as? String ?? "?"
            let data = try JSONSerialization.data(withJSONObject: ["message": v["message"]!, "workspace_name": "Workspace"])
            let q = try JSONCoding.decoder.decode(Question.self, from: data)
            let lead = ReviewStackRules.decisionFirst(try XCTUnwrap(ReviewStackRules.item(for: q), name))
            guard let shows = v["shows"] as? [String: Any] else { XCTAssertNil(lead, name + ": the card as before"); continue }
            XCTAssertEqual(lead?.decide, shows["decide"] as? String, name)
            XCTAssertEqual(lead?.ifWait, shows["if_wait"] as? String, name)
            XCTAssertEqual(lead?.facts, shows["facts"] as? [String], name)
        }
    }

    func testWithoutTheFlagTheCardIsAsBefore() throws {
        let old = try body(#"{"question_id":"q1","title":"Newsletter","text":"Send it Friday?","options":["Friday","Next week"],"recommended":null}"#)
        XCTAssertNil(old.decisionFirst); XCTAssertNil(old.ifWait); XCTAssertNil(old.facts)
        XCTAssertNil(ReviewStackRules.decisionFirst(try item(old)))
        // The lines alone do nothing, and a false flag is off.
        let lines = try body(#"{"question_id":"q1","text":"Send it Friday?","options":["a","b"],"recommended":null,"if_wait":"It slips.","facts":["x"],"decision_first":false}"#)
        XCTAssertNil(ReviewStackRules.decisionFirst(try item(lines)))
    }

    /// A plain question: the question leads, the ticket title is one quiet line, and the question is not said twice.
    func testPlainQuestionLeadsWithTheQuestion() throws {
        let b = try body(#"{"question_id":"q1","title":"Autumn newsletter","text":"Send it Friday?","options":["Friday","Next week"],"recommended":"Friday","decision_first":true,"if_wait":"The offer ends first.","facts":["1,400 readers","Legal said yes"]}"#)
        let it = try item(b)
        let lead = try XCTUnwrap(ReviewStackRules.decisionFirst(it))
        XCTAssertEqual(lead, DecisionFirst(decide: "Send it Friday?", title: "Autumn newsletter", ifWait: "The offer ends first.", facts: ["1,400 readers", "Legal said yes"]))
        XCTAssertEqual(it.card.then, lead.decide, "the card's own line repeats the question: the card view leaves it out")
        XCTAssertEqual(DecisionFirst.decideWord, "You decide:"); XCTAssertEqual(DecisionFirst.waitWord, "If you wait:"); XCTAssertEqual(DecisionFirst.factsTitle, "What matters")
    }

    func testTitleThatOnlyRepeatsTheQuestionIsShownOnce() throws {
        // No ticket title: the synthesized card's title is the question itself.
        let same = try body(#"{"question_id":"q1","text":"Send it Friday?","options":["a","b"],"recommended":null,"decision_first":true}"#)
        XCTAssertEqual(ReviewStackRules.decisionFirst(try item(same)), DecisionFirst(decide: "Send it Friday?", title: nil, ifWait: nil, facts: []))
        // A title that is the cut start of the question.
        let cut = try body(#"{"question_id":"q1","title":"Send it…","text":"Send it Friday?","options":["a","b"],"recommended":null,"decision_first":true}"#)
        XCTAssertNil(ReviewStackRules.decisionFirst(try item(cut))?.title)
    }

    /// A card question (draft, choice, plan, link): its question leads and the card's title stays as the quiet line.
    func testCardQuestionKeepsItsTitleAsTheQuietLine() throws {
        var b = QuestionBody(questionId: "q2", title: "Ticket", text: "Is the tone right for customers?", options: [], recommended: nil,
                             digest: String(repeating: "a", count: 64), card: ReviewCard(kind: .draft, title: "Newsletter draft", then: "I send it."))
        b.decisionFirst = true; b.ifWait = "It goes out a week late."
        let lead = try XCTUnwrap(ReviewStackRules.decisionFirst(try item(b)))
        XCTAssertEqual(lead, DecisionFirst(decide: "Is the tone right for customers?", title: "Newsletter draft", ifWait: "It goes out a week late.", facts: []))
    }

    /// A Test results card leads with its result and a command card with its command: neither is drawn decision-first.
    func testTestResultsAndCommandCardsStayAsTheyAre() throws {
        var check = QuestionBody(questionId: "review-1", title: "T", text: "Is this done?", options: ["accept", "changes"], recommended: nil, review: true,
                                 digest: String(repeating: "a", count: 64), card: ReviewCard(kind: .check, title: "T", then: "The ticket is done."))
        check.decisionFirst = true; check.ifWait = "x"; check.facts = ["y"]
        let it = try item(check)
        XCTAssertEqual(it.kind, .check); XCTAssertNil(ReviewStackRules.decisionFirst(it))
        XCTAssertEqual(ReviewStackRules.countsText([it]), "1 test result", "the card's name is Test results (docs/wording.md)")
    }

    /// What the workspace sends is data: more than four facts, long lines, line breaks and wrong types never break the card.
    func testLinesAreCutAndWrongTypesAreDropped() throws {
        let long = String(repeating: "x", count: 300)
        let b = try body(#"{"question_id":"q1","text":"Ship?","options":["a","b"],"recommended":null,"decision_first":true,"if_wait":"one\ntwo   three","facts":["a","  ","b","c","d","e","\#(long)"]}"#)
        let lead = try XCTUnwrap(ReviewStackRules.decisionFirst(try item(b)))
        XCTAssertEqual(lead.ifWait, "one two three")
        XCTAssertEqual(lead.facts, ["a", "b", "c", "d"], "at most four, empty ones left out")
        var cut = b; cut.facts = [long]; cut.ifWait = long
        let l2 = try XCTUnwrap(ReviewStackRules.decisionFirst(try item(cut)))
        XCTAssertEqual(l2.facts.first?.count, DecisionFirst.maxLine); XCTAssertEqual(l2.ifWait?.count, DecisionFirst.maxLine)
        // Wrong types: the question still arrives, without the lines it could not read.
        let bad = try body(#"{"question_id":"q1","text":"Ship?","options":["a","b"],"recommended":null,"decision_first":"yes","if_wait":7,"facts":[1,2]}"#)
        XCTAssertEqual(bad.text, "Ship?"); XCTAssertNil(bad.decisionFirst); XCTAssertNil(bad.ifWait); XCTAssertNil(bad.facts)
        let half = try body(#"{"question_id":"q1","text":"Ship?","options":["a","b"],"recommended":null,"decision_first":true,"facts":"no list"}"#)
        XCTAssertEqual(ReviewStackRules.decisionFirst(try item(half)), DecisionFirst(decide: "Ship?", title: nil, ifWait: nil, facts: []))
    }

    /// The fields survive the phone's own store (questions are saved and read back with the same coder).
    func testRoundTripKeepsTheLines() throws {
        var b = QuestionBody(questionId: "q1", title: nil, text: "Ship?", options: ["a", "b"], recommended: nil)
        b.decisionFirst = true; b.ifWait = "It waits."; b.facts = ["One"]
        let back = try JSONCoding.decoder.decode(QuestionBody.self, from: JSONCoding.encoder.encode(b))
        XCTAssertEqual(back, b)
        XCTAssertTrue(String(decoding: try JSONCoding.encoder.encode(b), as: UTF8.self).contains(#""decision_first":true"#))
        let plain = QuestionBody(questionId: "q1", title: nil, text: "Ship?", options: ["a", "b"], recommended: nil)
        XCTAssertFalse(String(decoding: try JSONCoding.encoder.encode(plain), as: UTF8.self).contains("decision_first"))
    }
}
