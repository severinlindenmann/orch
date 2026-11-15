import XCTest
@testable import OrchMobile

private func tmpDir() -> URL {
    let d = FileManager.default.temporaryDirectory.appendingPathComponent("rs-" + UUID().uuidString)
    try! FileManager.default.createDirectory(at: d, withIntermediateDirectories: true); return d
}
private func vectors() throws -> [String: Any] {
    // Copy of contracts/vectors/review-card-v1.json (Fixtures/).
    let url = Bundle(for: BundleToken.self).url(forResource: "review-card-v1", withExtension: "json")!
    return try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
}
private func shapes() throws -> [[String: Any]] { try vectors()["question_shapes"] as! [[String: Any]] }
private func question(_ name: String) throws -> Question {
    let s = try shapes().first { $0["name"] as? String == name }!
    let m = try JSONCoding.decoder.decode(QuestionMessage.self, from: JSONSerialization.data(withJSONObject: s["message"]!))
    return Question(message: m, workspaceName: "Pilatus")
}
private func plain(_ id: String, options: [String], at: String = "2026-11-15T10:00:00Z", qid: String = "q1", text: String? = nil, extra: (inout QuestionBody) -> Void = { _ in }) -> Question {
    var b = QuestionBody(questionId: qid, title: nil, text: text ?? "Which? " + id, options: options, recommended: nil)
    extra(&b)
    return Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: "ws_p", to: "phones", type: "question", createdAt: at, ticket: "t_" + id, body: b), workspaceName: "P")
}
private func cardQ(_ id: String, _ card: ReviewCard, at: String = "2026-11-15T10:00:00Z", ws: String = "ws_p", review: Bool = false) -> Question {
    let b = QuestionBody(questionId: review ? "review-1" : "q" + id, title: card.title, text: card.title, options: review ? ["accept", "changes"] : [],
                         recommended: nil, review: review ? true : nil, digest: String(repeating: "a", count: 64), card: card)
    return Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: ws, to: "phones", type: "question", createdAt: at, ticket: "t_" + id, body: b), workspaceName: "P")
}
private let draft = ReviewCard(kind: .draft, title: "D", then: "t", okLabel: "Send it")

final class ReviewCardCodableTests: XCTestCase {
    func testValidVectorQuestionsRoundTripCard() throws {
        var n = 0
        for s in try shapes() where s["schema"] as? Bool == true {
            let body = (s["message"] as! [String: Any])["body"] as! [String: Any]
            let name = s["name"] as! String
            let q = try question(name)
            XCTAssertEqual(q.message.body.digest, body["digest"] as? String, name)
            guard let wireCard = body["card"] as? [String: Any] else { continue }
            let card = try XCTUnwrap(q.message.body.card, "\(name) must decode")
            let enc = try JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(card)) as! NSDictionary
            XCTAssertEqual(enc, wireCard as NSDictionary, name)
            if let files = body["card_files"] as? [[String: Any]] {
                let enc = try JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(try XCTUnwrap(q.message.body.cardFiles))) as! [NSDictionary]
                XCTAssertEqual(enc, files as [NSDictionary], name)
            }
            n += 1
        }
        XCTAssertGreaterThanOrEqual(n, 5)
    }
    func testSrcFileAndUnavailableAndShapes() throws {
        let heldBack = try question("src-held-back").message.body.card
        if case .img(let src, _)? = heldBack?.preview { XCTAssertEqual(src, .unavailable(why: "held_back")) } else if case .page(let src)? = heldBack?.preview { XCTAssertEqual(src, .unavailable(why: "held_back")) } else { XCTFail("no src") }
        let choice = try question("card-choice").message.body.card
        guard case .options(let o)? = choice?.preview else { return XCTFail("options") }
        XCTAssertEqual(o.map(\.id), ["A", "B", "C"])
        XCTAssertEqual(o[0].preview, .img(src: .file(0), alt: nil))
        XCTAssertTrue(try question("card-signs-no-files").message.body.card?.requiresSignature == true)
    }
    func testUnreadableCardLeavesAPlainQuestion() throws {
        // Unknown preview type and unknown kind: the question stays, without card and card_files.
        let json = #"{"schema":"orch.msg/1","id":"m_x","from":"ws_p","to":"phones","type":"question","created_at":"2026-11-15T09:00:00Z","body":{"question_id":"q1","text":"T","options":[],"digest":"\#(String(repeating: "b", count: 64))","card":{"kind":"draft","title":"t","then":"x","preview":{"type":"hologram"}},"card_files":[{"blob_id":"b_1","name":"a.png","size":1,"sha256":"\#(String(repeating: "c", count: 64))","mime":"image/png"}]}}"#
        let m = try JSONCoding.decoder.decode(QuestionMessage.self, from: Data(json.utf8))
        XCTAssertNil(m.body.card); XCTAssertNil(m.body.cardFiles); XCTAssertEqual(m.body.text, "T")
        XCTAssertNil(ReviewStackRules.kind(of: Question(message: m, workspaceName: "P")))
    }
    func testOldQuestionDecodesAsBefore() throws {
        let json = #"{"schema":"orch.msg/1","id":"m_o","from":"ws_p","to":"phones","type":"question","created_at":"2026-11-15T09:00:00Z","body":{"question_id":"q1","text":"T","options":["a","b"],"recommended":"a"}}"#
        let m = try JSONCoding.decoder.decode(QuestionMessage.self, from: Data(json.utf8))
        XCTAssertNil(m.body.card); XCTAssertNil(m.body.digest); XCTAssertEqual(m.body.recommended, "a")
    }
    func testReviewResultParsedAndHiddenFromChat() throws {
        let shapes = try vectors()["review_result_shapes"] as! [[String: Any]]
        for s in shapes where s["schema"] as? Bool == true {
            let m = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: s["message"]!))
            XCTAssertTrue(m.body.isReviewResult, s["name"] as! String)
            XCTAssertNotNil(m.replyTo)
        }
        let applied = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: shapes[0]["message"]!))
        XCTAssertEqual(applied.body.reviewResult?.result, "applied")
        let unknown = #"{"schema":"orch.msg/1","id":"m_u","from":"ws_p","to":"ph_1","type":"text","created_at":"2026-11-15T09:00:00Z","body":{"text":"x","review_result":{"result":"weird"}}}"#
        XCTAssertFalse(try JSONCoding.decoder.decode(TextMessage.self, from: Data(unknown.utf8)).body.isReviewResult)
    }
    func testAnswerRequestVerdictVectorsEncode() throws {
        for c in try vectors()["answer_requests"] as! [[String: Any]] where c["schema"] as? Bool == true {
            let r = try JSONCoding.decoder.decode(AnswerRequest.self, from: JSONSerialization.data(withJSONObject: c["request"]!))
            let enc = try JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(r)) as! NSDictionary
            func strip(_ x: Any) -> Any {          // a null `picked` is left out when the phone encodes
                if let d = x as? [String: Any] { return d.filter { !($0.value is NSNull) }.mapValues(strip) }
                return x
            }
            XCTAssertEqual(enc, strip(c["request"]!) as! NSDictionary, c["name"] as! String)
            XCTAssertTrue(r.verdict?.isValid ?? true, c["name"] as! String)
        }
        // no verdict: the old body, byte for byte the old keys
        let plain = try JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(AnswerRequest(questionMessageId: "m_1", answer: "a", clientId: "c"))) as! [String: Any]
        XCTAssertEqual(Set(plain.keys), ["question_message_id", "answer", "client_id"])
    }
}

final class ReviewStackRulesTests: XCTestCase {
    func testStackKindsAndExclusions() throws {
        let allow = plain("m_allow", options: ["once", "always", "no"]) { $0.allowQuestion = true }
        let proposal = plain("m_prop", options: ["make", "not_now"], qid: "proposal-m_prop") { $0.proposal = "make_ticket" }
        let group = plain("m_group", options: ["a", "b"]) { $0.groupRef = GroupRef(host: "ws_h", id: "g_1") }
        let free = plain("m_free", options: [])
        let one = plain("m_one", options: ["only"])
        let ok = plain("m_ok", options: ["Yes", "No"])
        let q = [allow, proposal, group, free, one, ok, cardQ("m_card", draft)]
        let stack = ReviewStackRules.stack(questions: q, answers: [:])
        XCTAssertEqual(Set(stack.map(\.id)), ["m_ok", "m_card"])
        XCTAssertEqual(stack.first { $0.id == "m_ok" }?.kind, .plainQuestion)
        XCTAssertEqual(stack.first { $0.id == "m_ok" }?.optionIds, ["A", "B"])
        XCTAssertEqual(stack.first { $0.id == "m_card" }?.kind, .draft)
    }
    func testReviewQuestionBecomesCheckCard() {
        let withCard = cardQ("m_r1", ReviewCard(kind: .check, title: "Done?", then: "Moves on"), review: true)
        var b = QuestionBody(questionId: "review-2", title: "T", text: "Is it done?", options: ["accept", "changes"], recommended: nil, review: true)
        b.digest = nil
        let bare = Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_r2", from: "ws_p", to: "phones", type: "question", createdAt: "2026-11-15T10:01:00Z", ticket: "t_2", body: b), workspaceName: "P")
        let s = ReviewStackRules.stack(questions: [withCard, bare], answers: [:])
        XCTAssertEqual(s.map(\.kind), [.check, .check])
        XCTAssertNil(s[1].digest)
        XCTAssertEqual(ReviewStackRules.legacyAnswer(s[1], picked: nil), "accept")
    }
    func testCheckCardOnPlainQuestionIsNotAStackCard() {
        XCTAssertNil(ReviewStackRules.kind(of: cardQ("m_bad", ReviewCard(kind: .check, title: "x", then: "y"))))
    }
    func testAnsweredAndPendingLeaveTheStack() {
        let a = cardQ("m_a", draft, at: "2026-11-15T10:00:00Z"), b = cardQ("m_b", draft, at: "2026-11-15T10:01:00Z"), c = cardQ("m_c", draft, at: "2026-11-15T10:02:00Z")
        XCTAssertEqual(ReviewStackRules.stack(questions: [c, b, a], answers: ["m_a": "x"], pending: ["m_b"]).map(\.id), ["m_c"])
        XCTAssertEqual(ReviewStackRules.stack(questions: [c, b, a], answers: [:]).map(\.id), ["m_a", "m_b", "m_c"])
        XCTAssertEqual(ReviewStackRules.stack(questions: [c, b, a], answers: [:], workspace: "ws_other").count, 0)
    }
    func testLaterGoesToTheEndInMoveOrderAndPersistsPerWorkspace() {
        let qs = ["m_a", "m_b", "m_c", "m_d"].enumerated().map { cardQ($1, draft, at: "2026-11-15T10:0\($0):00Z") }
        XCTAssertEqual(ReviewStackRules.stack(questions: qs, answers: [:], later: ["m_c", "m_a"]).map(\.id), ["m_b", "m_d", "m_c", "m_a"])
        let suite = "rs-later-" + UUID().uuidString
        let d = UserDefaults(suiteName: suite)!; defer { d.removePersistentDomain(forName: suite) }
        let store = LaterStore(defaults: d)
        store.push("m_a", workspace: "ws_p"); store.push("m_b", workspace: "ws_p"); store.push("m_a", workspace: "ws_p"); store.push("m_z", workspace: "ws_q")
        XCTAssertEqual(LaterStore(defaults: d).ids(workspace: "ws_p"), ["m_b", "m_a"])      // a new instance = after a restart
        XCTAssertEqual(store.ids(workspace: "ws_q"), ["m_z"])
        store.prune(keeping: ["m_a"], workspace: "ws_p"); XCTAssertEqual(store.ids(workspace: "ws_p"), ["m_a"])
        store.remove("m_a", workspace: "ws_p"); XCTAssertEqual(store.ids(workspace: "ws_p"), [])
    }
    func testCountsText() {
        func item(_ id: String, _ c: ReviewCard) -> ReviewItem { ReviewStackRules.item(for: cardQ(id, c))! }
        let choice = ReviewCard(kind: .choice, title: "c", then: "t", preview: .options([CardOption(id: "A", title: "a"), CardOption(id: "B", title: "b")]))
        let items = [item("1", draft), item("2", draft), item("3", draft), item("4", choice), item("5", choice),
                     ReviewStackRules.item(for: cardQ("6", ReviewCard(kind: .check, title: "k", then: "t"), review: true))!,
                     ReviewStackRules.item(for: cardQ("7", ReviewCard(kind: .check, title: "k", then: "t"), review: true))!,
                     item("8", ReviewCard(kind: .plan, title: "p", then: "t"))]
        XCTAssertEqual(ReviewStackRules.countsText(items), "3 drafts · 2 choices · 2 results · 1 plan")
        XCTAssertEqual(ReviewStackRules.countsText([items[0]]), "1 draft")
        XCTAssertEqual(ReviewStackRules.countsText([]), "")
    }
    func testNeedsYouFilterShowsStackQuestionsOnlyInTheStack() {
        let stackQ = cardQ("m_s", draft), plainChoice = plain("m_p", options: ["Yes", "No"])
        let free = plain("m_f", options: []), allow = plain("m_al", options: ["once", "always", "no"]) { $0.allowQuestion = true }
        _ = free
        let remaining = ReviewStackRules.withoutStackQuestions([stackQ, plainChoice, free, allow])
        XCTAssertEqual(remaining.map(\.id), ["m_f", "m_al"])
        XCTAssertEqual(ChatsRowRules.needsYou(remaining, answers: [:]).map(\.id), ["m_f", "m_al"])
    }
    func testSummaryLines() {
        let item = ReviewStackRules.item(for: cardQ("m_s", draft))!
        let d = String(repeating: "a", count: 64)
        XCTAssertEqual(ReviewStackRules.summary(item, verdict: ReviewVerdict(verdict: .ok, digest: d)), "Send it")
        XCTAssertEqual(ReviewStackRules.summary(item, verdict: ReviewVerdict(verdict: .ok, picked: "C", digest: d)), "Use C")
        let note = ReviewVerdict.Note(changes: ["x", "y"])
        XCTAssertEqual(ReviewStackRules.summary(item, verdict: ReviewVerdict(verdict: .talk, picked: "C", digest: d, note: note)), "Use C with 2 changes")
        let words = ReviewVerdict.Note(words: .init(text: "Use the new address"))
        XCTAssertEqual(ReviewStackRules.summary(item, verdict: ReviewVerdict(verdict: .talk, digest: d, note: words)), "Send back for changes: Use the new address")
    }
}

final class SwipeThresholdTests: XCTestCase {
    let size = CGSize(width: 400, height: 600)
    func testDistanceNeeded() {
        XCTAssertEqual(ReviewStackRules.goes(dx: 121, dy: 0, speed: 0, size: size), .right)
        XCTAssertNil(ReviewStackRules.goes(dx: 119, dy: 0, speed: 0, size: size))
        XCTAssertEqual(ReviewStackRules.goes(dx: -121, dy: 10, speed: 100, size: size), .left)
        XCTAssertEqual(ReviewStackRules.goes(dx: 0, dy: 133, speed: 0, size: size), .down)       // 22 % of 600 = 132
        XCTAssertNil(ReviewStackRules.goes(dx: 0, dy: -130, speed: 0, size: size))
        XCTAssertEqual(ReviewStackRules.goes(dx: 0, dy: -133, speed: 0, size: size), .up)
    }
    func testFlickNeedsSpeedAndSmallerDistance() {
        XCTAssertEqual(ReviewStackRules.goes(dx: 81, dy: 0, speed: 601, size: size), .right)    // 20 % of 400 = 80
        XCTAssertNil(ReviewStackRules.goes(dx: 81, dy: 0, speed: 600, size: size))
        XCTAssertNil(ReviewStackRules.goes(dx: 79, dy: 0, speed: 2000, size: size))             // a flick alone is no approval
        XCTAssertEqual(ReviewStackRules.goes(dx: 0, dy: 91, speed: 700, size: size), .down)     // 15 % of 600 = 90
        XCTAssertNil(ReviewStackRules.goes(dx: 0, dy: 89, speed: 700, size: size))
    }
    func testDirectionBiasAndLeftEdge() {
        XCTAssertEqual(ReviewStackRules.direction(dx: 100, dy: 105), .right)    // vertical must be 10 % clearer
        XCTAssertEqual(ReviewStackRules.direction(dx: 100, dy: 120), .down)
        XCTAssertTrue(ReviewStackRules.startsAtLeftEdge(x: 15.9)); XCTAssertFalse(ReviewStackRules.startsAtLeftEdge(x: 16))
    }
}

@MainActor
final class ReviewVerdictOutboxTests: XCTestCase {
    private var dirs: [URL] = []
    override func setUp() { UserDefaults.standard.set(true, forKey: "mockReviewStack") }
    override func tearDown() { UserDefaults.standard.removeObject(forKey: "mockReviewStack"); Outbox.flushAllWrites(); for d in dirs { try? FileManager.default.removeItem(at: d) }; dirs = [] }
    private func outbox() -> (Outbox, URL) { let d = tmpDir(); dirs.append(d); return (Outbox(directory: d, phone: "ph_iphone0001"), d) }
    private func ok(_ q: Question) -> ReviewVerdict { ReviewVerdict(verdict: .ok, digest: q.message.body.digest!) }

    func testVerdictAnswerIsPersistedAndSentWithVerdict() async throws {
        let (box, dir) = outbox(); let q = try question("card-draft")
        let item = try box.enqueueAnswer(question: q, answer: "Send it", verdict: ok(q))
        XCTAssertEqual(ReviewStackRules.state(item: box.item(clientId: item.clientId), result: nil), .savedOnPhone)
        box.flushWrites()
        let again = Outbox(directory: dir, phone: "ph_iphone0001")                              // a restart
        XCTAssertEqual(again.items.first?.verdict, ok(q))
        let wire = Outbox.answerRequest(for: again.items[0])
        XCTAssertEqual(wire.verdict, ok(q)); XCTAssertEqual(wire.answer, "Send it"); XCTAssertEqual(wire.clientId, item.clientId)
    }
    func testOfflineKeepsItThenSentThenResultStates() async throws {
        let (box, _) = outbox(); let q = MockReviewStack.questions[0]
        let relay = MockRelay(latency: .zero)
        let item = try box.enqueueAnswer(question: q, answer: "Send it", verdict: ok(q))
        await relay.setOffline(true)
        let off = await box.flush(using: relay)
        XCTAssertEqual(off, [.offline]); XCTAssertEqual(box.items.count, 1)
        XCTAssertEqual(ReviewStackRules.state(item: box.items[0], result: nil), .savedOnPhone)
        XCTAssertTrue(box.items[0].canChangeVerdict)
        await relay.setOffline(false)
        _ = await box.flush(using: relay)
        XCTAssertEqual(ReviewStackRules.state(item: box.items[0], result: nil), .sent)     // stays until the result
        XCTAssertFalse(box.items[0].canChangeVerdict)
        let (cid, qid) = (item.clientId, item.questionMessageId!)
        let result = ReviewResult(result: "applied", summary: "Send it")
        XCTAssertEqual(ReviewStackRules.state(item: box.item(clientId: cid), result: result), .received(summary: "Send it"))
        XCTAssertEqual(ReviewStackRules.state(item: nil, result: ReviewResult(result: "changed")), .changed)
        XCTAssertEqual(ReviewStackRules.state(item: nil, result: ReviewResult(result: "refused", reason: "needs_signature")), .refused(reason: "needs_signature"))
        XCTAssertEqual(ReviewStackRules.state(item: nil, result: ReviewResult(result: "decided", summary: "Other")), .decided(summary: "Other"))
        XCTAssertNil(ReviewStackRules.state(item: nil, result: nil))
        // the result text arrives in /messages: the item leaves the outbox
        let msg = PhoneMessage(message: TextMessage(id: "m_res1", from: "ws_pilatus001", to: "ph_iphone0001", type: "text", createdAt: "2026-11-15T09:02:00Z", ticket: nil,
                                                    body: TextBody(text: "Got it", reviewResult: result), replyTo: qid), workspaceName: "P")
        XCTAssertEqual(ReviewStackRules.result(for: qid, workspace: "ws_pilatus001", in: [msg])?.result, "applied")
        // a result from another workspace with the same replyTo is ignored by both
        let other = PhoneMessage(message: TextMessage(id: "m_res2", from: "ws_other0001", to: "ph_iphone0001", type: "text", createdAt: "2026-11-15T09:03:00Z", ticket: nil,
                                                      body: TextBody(text: "x", reviewResult: result), replyTo: qid), workspaceName: "O")
        XCTAssertNil(ReviewStackRules.result(for: qid, workspace: "ws_pilatus001", in: [other]))
        box.reconcile(with: [other]); XCTAssertEqual(box.items.count, 1)
        box.reconcile(with: [msg]); XCTAssertTrue(box.items.isEmpty)
        let verdicts = await relay.verdicts
        XCTAssertEqual(verdicts.count, 1); XCTAssertEqual(verdicts[0].verdict, ok(q))
    }
    func testChangeOnlyWhileInTheOutbox() throws {
        let (box, _) = outbox(); let q = try question("card-choice")
        let a = ReviewVerdict(verdict: .ok, picked: "A", digest: q.message.body.digest!)
        let b = ReviewVerdict(verdict: .ok, picked: "B", digest: q.message.body.digest!)
        let item = try box.enqueueAnswer(question: q, answer: "Use A", verdict: a)
        let changed = try box.changeVerdict(question: q, answer: "Use B", verdict: b)
        XCTAssertEqual(changed.clientId, item.clientId); XCTAssertEqual(changed.verdict, b); XCTAssertEqual(box.items.count, 1)
        // once the relay has it, it is final (M4)
        box.discard(item.clientId)
        let sentItem = try box.enqueueAnswer(question: q, answer: "Use A", verdict: a)
        var copy = box.item(clientId: sentItem.clientId)!; copy.sentMessageId = "m_s"
        XCTAssertFalse(copy.canChangeVerdict)
    }
    func testChangeAfterSentIsRefused() async throws {
        let (box, _) = outbox(); let q = MockReviewStack.questions[0]; let relay = MockRelay(latency: .zero)
        try box.enqueueAnswer(question: q, answer: "Send it", verdict: ok(q))
        _ = await box.flush(using: relay)
        XCTAssertThrowsError(try box.changeVerdict(question: q, answer: "No", verdict: ReviewVerdict(verdict: .no, digest: q.message.body.digest!))) {
            XCTAssertEqual($0 as? Outbox.VerdictProblem, .alreadySent)
        }
    }
    func testSignsCardNeverEnqueuesOk() throws {
        let (box, _) = outbox(); let q = try question("card-signs-no-files")
        XCTAssertTrue(q.message.body.card?.requiresSignature == true)
        XCTAssertThrowsError(try box.enqueueAnswer(question: q, answer: "OK", verdict: ok(q))) { XCTAssertEqual($0 as? Outbox.VerdictProblem, .needsSignature) }
        XCTAssertTrue(box.items.isEmpty)
        let item = ReviewStackRules.item(for: q)!
        XCTAssertEqual(ReviewStackRules.okOutcome(item, picked: nil), .needsSignature)
        XCTAssertEqual(ReviewStackRules.needsSignatureText, "Needs your signature on the computer")
        // a "no" is fine
        XCTAssertNoThrow(try box.enqueueAnswer(question: q, answer: "No", verdict: ReviewVerdict(verdict: .no, digest: q.message.body.digest!)))
    }
    func testInvalidVerdictsAreNotQueued() throws {
        let (box, _) = outbox(); let q = try question("card-choice"); let digest = q.message.body.digest!
        for bad in [ReviewVerdict(verdict: .ok, picked: "Z", digest: digest),                                            // not an option
                    ReviewVerdict(verdict: .ok, picked: "A", digest: String(repeating: "0", count: 64)),                  // other digest
                    ReviewVerdict(verdict: .talk, picked: "A", digest: digest),                                           // talk without words
                    ReviewVerdict(verdict: .no, picked: "A", digest: digest)] {
            XCTAssertThrowsError(try box.enqueueAnswer(question: q, answer: "x", verdict: bad)) { XCTAssertEqual($0 as? Outbox.VerdictProblem, .invalid) }
        }
        let big = ReviewVerdict(verdict: .talk, digest: digest, note: .init(words: .init(text: String(repeating: "é", count: 2000), voice: nil), pins: (1...30).map { .init(n: $0, x: 0.5, y: 0.5, text: String(repeating: "é", count: 500)) }))
        XCTAssertFalse(big.isValid)           // over 8 KB
        XCTAssertTrue(box.items.isEmpty)
    }
    func testChoiceNeedsPickFirst() throws {
        let item = ReviewStackRules.item(for: try question("card-choice"))!
        XCTAssertEqual(ReviewStackRules.okOutcome(item, picked: nil), .pickFirst)
        XCTAssertEqual(ReviewStackRules.okOutcome(item, picked: "Q"), .pickFirst)
        XCTAssertEqual(ReviewStackRules.okOutcome(item, picked: "B"), .allowed)
    }
    func testOldAnswerWithoutVerdictIsUnchanged() async throws {
        let (box, _) = outbox(); let relay = MockRelay(latency: .zero)
        let q = Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_q1date0ts0000001", from: MockRelay.pilatus, to: "phones", type: "question", createdAt: "2026-11-04T10:41:00Z", ticket: "t_7k3f9q",
                         body: QuestionBody(questionId: "q1", title: nil, text: "DATE or TIMESTAMP?", options: ["DATE", "TIMESTAMP"], recommended: nil)), workspaceName: "P")
        box.enqueueAnswer(question: q, answer: "DATE")
        let ev = await box.flush(using: relay)
        XCTAssertEqual(ev.count, 1); XCTAssertTrue(box.items.isEmpty)       // discarded as before
    }
    func testMockStackFixtureAndVerifiedBlobs() async throws {
        let relay = MockRelay(latency: .zero)
        let qs = try await relay.questions().filter { $0.id.hasPrefix("m_rvstack") }
        XCTAssertEqual(qs.count, 8)
        let items = ReviewStackRules.stack(questions: qs, answers: [:])
        XCTAssertEqual(ReviewStackRules.countsText(items), "3 drafts · 2 choices · 2 results · 1 plan")
        let compare = items.first { if case .compare? = $0.card.preview { true } else { false } }
        XCTAssertNotNil(compare)
        for f in qs.flatMap({ $0.message.body.cardFiles ?? [] }) {
            let data = try await relay.cardFile(f); XCTAssertEqual(data.count, f.size)
        }
        let bad = CardFile(blobId: "b_rv1f0", name: "invoice.png", size: 3, sha256: String(repeating: "0", count: 64), mime: "image/png")
        do { _ = try await relay.cardFile(bad); XCTFail("hash mismatch must fail") } catch RelayError.api(let s, _, _) { XCTAssertEqual(s, 422) }
        do { _ = try await relay.blob(id: "b_nope") ; XCTFail() } catch RelayError.api(let s, _, _) { XCTAssertEqual(s, 404) }
    }
}
