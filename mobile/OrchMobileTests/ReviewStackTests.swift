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
    func testStackGroupsByTicketThenTaskAndShowsAbout() throws {
        func q(_ id: String, ticket: String, task: String?, at: String) -> Question {
            var b = QuestionBody(questionId: "q" + id, title: "D", text: "D", options: [], recommended: nil, digest: String(repeating: "a", count: 64), card: draft)
            b.task = task; b.about = task.map { "Task " + $0 + "\nsecond line" }
            return Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: "ws_p", to: "phones", type: "question", createdAt: at, ticket: ticket, body: b), workspaceName: "P")
        }
        let qs = [q("m_1", ticket: "t_a", task: "c10", at: "2026-11-15T10:00:00Z"), q("m_2", ticket: "t_b", task: "c1", at: "2026-11-15T10:01:00Z"),
                  q("m_3", ticket: "t_a", task: nil, at: "2026-11-15T10:02:00Z"), q("m_4", ticket: "t_a", task: "c2", at: "2026-11-15T10:03:00Z"),
                  q("m_5", ticket: "t_a", task: "c2", at: "2026-11-15T10:02:30Z")]
        let items = ReviewStackRules.stack(questions: qs, answers: [:])
        XCTAssertEqual(items.map(\.id), ["m_5", "m_4", "m_1", "m_3", "m_2"])   // t_a waited longest; c2 before c10; no task last
        XCTAssertEqual(ReviewStackRules.aboutLine(items[0]), "About: Task c2 second line")
        XCTAssertNil(ReviewStackRules.aboutLine(items[3]))
        // an older workspace sends neither field: the card decodes as before
        let json = #"{"question_id":"q1","text":"Ship?","options":["yes","no"],"recommended":null,"task":7}"#
        let body = try JSONCoding.decoder.decode(QuestionBody.self, from: Data(json.utf8))
        XCTAssertNil(body.task); XCTAssertNil(body.about)
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
        XCTAssertNil(ReviewStackRules.goes(dx: 79, dy: 0, speed: 2000, size: size))             // a flick alone does nothing
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
        XCTAssertEqual(ReviewStackRules.state(item: nil, result: ReviewResult(result: "refused", reason: "invalid")), .refused(reason: "invalid"))
        XCTAssertEqual(ReviewStackRules.state(item: nil, result: ReviewResult(result: "decided", summary: "Other")), .decided(summary: "Other"))
        XCTAssertNil(ReviewStackRules.state(item: nil, result: nil))
        // the result text arrives in /messages: the item leaves the outbox
        let msg = PhoneMessage(message: TextMessage(id: "m_res1", from: "ws_pilatus001", to: "ph_iphone0001", type: "text", createdAt: "2999-01-01T00:00:00Z", ticket: nil,   // after the answer
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
    // ORCH-2126: once the POST may have reached the relay, Change and Undo must not claim to replace it.
    func testNoChangeWhileTheAnswerReplyIsPending() async throws {
        let (box, _) = outbox(); let q = MockReviewStack.questions[0]; let relay = MockRelay(latency: .zero)
        let no = ReviewVerdict(verdict: .no, digest: q.message.body.digest!)
        try box.enqueueAnswer(question: q, answer: "Send it", verdict: ok(q))
        await relay.setHoldAnswers(true)
        let flushing = Task { await box.flush(using: relay) }
        while await relay.heldAnswerCount == 0 { await Task.yield() }
        XCTAssertNil(box.items[0].sentMessageId)
        XCTAssertFalse(box.items[0].canChangeVerdict)              // hides Change, disables Undo
        XCTAssertThrowsError(try box.changeVerdict(question: q, answer: "No", verdict: no)) { XCTAssertEqual($0 as? Outbox.VerdictProblem, .alreadySent) }
        await relay.releaseAnswers()
        _ = await flushing.value
        XCTAssertNotNil(box.items[0].sentMessageId); XCTAssertEqual(box.items[0].verdict, ok(q))
        let verdicts = await relay.verdicts
        XCTAssertEqual(verdicts.map(\.verdict), [ok(q)])
    }
    func testLostReplyKeepsTheAnswerAndRetriesItUnchangedAfterARelaunch() async throws {
        let (box, dir) = outbox(); let q = MockReviewStack.questions[0]; let relay = MockRelay(latency: .zero)
        let item = try box.enqueueAnswer(question: q, answer: "Send it", verdict: ok(q))
        await relay.setLoseNextAnswerReply()                        // stored by the relay, reply lost
        let lost = await box.flush(using: relay)
        XCTAssertEqual(lost, [.offline])
        XCTAssertNil(box.items[0].sentMessageId); XCTAssertFalse(box.items[0].canChangeVerdict)
        XCTAssertThrowsError(try box.changeVerdict(question: q, answer: "No", verdict: ReviewVerdict(verdict: .no, digest: q.message.body.digest!))) {
            XCTAssertEqual($0 as? Outbox.VerdictProblem, .alreadySent)
        }
        let again = Outbox(directory: dir, phone: "ph_iphone0001")  // a relaunch
        XCTAssertFalse(again.items[0].canChangeVerdict)
        let events = await again.flush(using: relay)
        XCTAssertEqual(events, [.answered(clientId: item.clientId, questionMessageId: q.id, answer: "Send it")])
        let sent = await relay.answerRequests
        XCTAssertEqual(sent.count, 2); XCTAssertEqual(sent[1], sent[0]); XCTAssertEqual(sent[1].clientId, item.clientId)
        let verdicts = await relay.verdicts
        XCTAssertEqual(verdicts.count, 1)
        XCTAssertNotNil(again.items[0].sentMessageId)
    }
    func testLostReplyIsClosedByTheWorkspaceResultAfterARelaunch() async throws {
        let (box, dir) = outbox(); let q = MockReviewStack.questions[0]; let relay = MockRelay(latency: .zero)
        try box.enqueueAnswer(question: q, answer: "Send it", verdict: ok(q))
        await relay.setLoseNextAnswerReply()
        _ = await box.flush(using: relay)
        let again = Outbox(directory: dir, phone: "ph_iphone0001")
        let msg = PhoneMessage(message: TextMessage(id: "m_res1", from: q.message.from, to: "ph_iphone0001", type: "text", createdAt: "2999-01-01T00:00:00Z", ticket: nil,
                                                    body: TextBody(text: "Got it", reviewResult: ReviewResult(result: "applied", summary: "Send it")), replyTo: q.id), workspaceName: "P")
        again.reconcile(with: [msg])
        XCTAssertTrue(again.items.isEmpty)
    }
    func testRefusedOrUnreachedAnswerStaysChangeable() async throws {
        let (box, _) = outbox(); let q = cardQ("m_notonrelay01", draft); let relay = MockRelay(latency: .zero)
        try box.enqueueAnswer(question: q, answer: "Send it", verdict: ok(q))
        let events = await box.flush(using: relay)                  // 404: the relay refused it, nothing stored
        XCTAssertEqual(events.count, 1); XCTAssertNotNil(box.items[0].failure)
        XCTAssertTrue(box.items[0].canChangeVerdict)
        XCTAssertTrue(Outbox.neverStored(URLError(.notConnectedToInternet)))
        XCTAssertTrue(Outbox.neverStored(RelayError.api(status: 422, code: "invalid", message: "x")))
        for maybe: Error in [URLError(.networkConnectionLost), URLError(.timedOut), RelayError.api(status: 408, code: "x", message: "x"),
                             RelayError.api(status: 503, code: "x", message: "x"), RelayError.network("x")] {
            XCTAssertFalse(Outbox.neverStored(maybe), "\(maybe)")
        }
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
    // ORCH-444: voice notes, pictures and files with a Send back
    private func draftFile(_ name: String, _ data: Data, kind: MessageAttachment.Kind, mime: String, duration: Double? = nil) throws -> DraftFile {
        let d = tmpDir(); dirs.append(d)
        let url = d.appendingPathComponent(name); try data.write(to: url)
        return DraftFile(url: url, kind: kind, name: name, mime: mime, duration: duration)
    }
    func testAnswerFilesAreUploadedFirstAndNamedInTheVerdict() async throws {
        let (box, dir) = outbox(); let q = MockReviewStack.questions[0]; let relay = MockRelay(latency: .zero)
        let jpg = Data([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]), voice = Data(repeating: 7, count: 40)
        let photo = try draftFile("screen.jpg", jpg, kind: .image, mime: "image/jpeg")
        let rec = try draftFile("voice-1.m4a", voice, kind: .voice, mime: "audio/mp4", duration: 2.4)
        let v = ReviewVerdict(verdict: .talk, digest: q.message.body.digest!, note: .init(words: .init(text: "Bigger logo")))
        try box.enqueueAnswer(question: q, answer: "Send back for changes: Bigger logo", verdict: v, files: [photo, rec])
        try FileManager.default.removeItem(at: photo.url)                              // the Outbox keeps its own copy
        XCTAssertEqual(box.items[0].files.map(\.name), ["screen.jpg", "voice-1.m4a"])
        XCTAssertNil(box.items[0].verdict?.note?.files, "blob ids are only known after the upload")
        box.flushWrites()
        let again = Outbox(directory: dir, phone: "ph_iphone0001")                    // a restart keeps the files
        XCTAssertEqual(again.items[0].files.count, 2)
        _ = await again.flush(using: relay)
        let verdicts = await relay.verdicts, uploads = await relay.uploads
        let files = try XCTUnwrap(verdicts.first?.verdict.note?.files)
        XCTAssertEqual(files.map(\.kind), [.image, .voice]); XCTAssertEqual(files.map(\.size), [jpg.count, voice.count])
        XCTAssertEqual(uploads[files[0].blobId], jpg); XCTAssertEqual(uploads[files[1].blobId], voice)
        XCTAssertEqual(files[1].duration, 2.4); XCTAssertEqual(verdicts[0].verdict.note?.words?.text, "Bigger logo")
    }
    func testFilesAloneAreEnoughAndAtMostFive() throws {
        let (box, _) = outbox(); let q = MockReviewStack.questions[0]; let digest = q.message.body.digest!
        let one = try draftFile("offer.pdf", Data("%PDF".utf8), kind: .file, mime: "application/pdf")
        let talk = ReviewVerdict(verdict: .talk, digest: digest)
        XCTAssertEqual(ReviewStackRules.summary(ReviewStackRules.item(for: q)!, verdict: talk, files: 1), "Send back for changes (1 file)")
        XCTAssertThrowsError(try box.enqueueAnswer(question: q, answer: "x", verdict: talk, files: Array(repeating: one, count: 6))) {
            XCTAssertEqual($0 as? Outbox.VerdictProblem, .invalid)
        }
        XCTAssertTrue(box.items.isEmpty)
        try box.enqueueAnswer(question: q, answer: "Send back for changes (1 file)", verdict: talk, files: [one])
        XCTAssertEqual(Outbox.answerRequest(for: box.items[0]).verdict?.note?.files?.count, 1)
    }
    func testChangingTheVerdictReplacesItsFiles() throws {
        let (box, _) = outbox(); let q = MockReviewStack.questions[0]; let digest = q.message.body.digest!
        let one = try draftFile("offer.pdf", Data("%PDF".utf8), kind: .file, mime: "application/pdf")
        try box.enqueueAnswer(question: q, answer: "x", verdict: ReviewVerdict(verdict: .talk, digest: digest), files: [one])
        try box.changeVerdict(question: q, answer: "Send it", verdict: ok(q))
        XCTAssertTrue(box.items[0].files.isEmpty)
        XCTAssertNil(Outbox.answerRequest(for: box.items[0]).verdict?.note, "a right swipe carries no files")
    }
    /// Codex review: a replacement that cannot be copied left the old answer pointing at deleted copies.
    func testAFailedReplacementKeepsTheOldFiles() throws {
        let (box, _) = outbox(); let q = MockReviewStack.questions[0]; let digest = q.message.body.digest!
        let one = try draftFile("offer.pdf", Data("%PDF".utf8), kind: .file, mime: "application/pdf")
        let talk = ReviewVerdict(verdict: .talk, digest: digest)
        try box.enqueueAnswer(question: q, answer: "x", verdict: talk, files: [one])
        let empty = try draftFile("empty.jpg", Data(), kind: .image, mime: "image/jpeg")
        XCTAssertThrowsError(try box.changeVerdict(question: q, answer: "y", verdict: talk, files: [empty]))
        let kept = try XCTUnwrap(box.items[0].files.first)
        XCTAssertEqual(kept.name, "offer.pdf")
        XCTAssertTrue(FileManager.default.fileExists(atPath: box.fileURL(box.items[0], kept).path))
        let two = try draftFile("screen.jpg", Data([0xff, 0xd8, 1]), kind: .image, mime: "image/jpeg")
        try box.changeVerdict(question: q, answer: "z", verdict: talk, files: [two])
        XCTAssertEqual(box.items[0].files.map(\.name), ["screen.jpg"])
        XCTAssertNotEqual(box.items[0].files[0].file, kept.file, "a replacement never reuses an old copy's name")
        XCTAssertFalse(FileManager.default.fileExists(atPath: box.fileURL(box.items[0], kept).path), "the old copy goes")
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
        XCTAssertEqual(qs.count, 7)
        let items = ReviewStackRules.stack(questions: qs, answers: [:])
        XCTAssertEqual(ReviewStackRules.countsText(items), "3 drafts · 2 choices · 1 result · 1 plan")
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

@MainActor
final class CardFileCacheTests: XCTestCase {
    /// A blob already in the plain blob cache (no hash check) is never served as a card file with another hash.
    func testCachedBlobWithDifferentHashIsNotReturnedAsCardFile() async throws {
        let model = AppModel(useMock: true)
        let good = try XCTUnwrap(MockReviewStack.questions[0].message.body.cardFiles?.first)
        _ = await model.blob(good.blobId)                         // fills blobCache without a hash check
        let forged = CardFile(blobId: good.blobId, name: good.name, size: good.size, sha256: String(repeating: "0", count: 64), mime: good.mime)
        let bad = await model.cardFile(forged)
        XCTAssertNil(bad)
        let ok = await model.cardFile(good)
        XCTAssertNotNil(ok)
        let again = await model.cardFile(forged)                  // a verified cache hit for another hash does not leak either
        XCTAssertNil(again)
    }
}

/// ORCH-860: Run it now on the phone. A run card shows the command with Copy; Run it now only for orch's own commands the
/// computer marked for the phone; every other command shows one line why and a right swipe never sends ok.
final class RunCardTests: XCTestCase {
    func testRunShapesDecodeOnlyWhenTheSchemaTakesThem() throws {
        var n = 0
        for s in try shapes() where (s["name"] as! String).hasPrefix("card-run-") || (s["name"] as! String).hasPrefix("run-") {
            let name = s["name"] as! String
            // an extra key (folder, argv) is refused by the relay; the app ignores unknown keys like on every card and never shows them
            if ["run-cwd-on-wire", "run-argv-on-wire"].contains(name) { continue }
            let card = try question(name).message.body.card
            if s["schema"] as? Bool == true { XCTAssertEqual(card?.kind, .run, name) } else { XCTAssertNil(card, name) }
            n += 1
        }
        XCTAssertGreaterThanOrEqual(n, 28)
    }
    func testOrchCommandRunsHereOthersShowWhy() throws {
        let orch = ReviewStackRules.item(for: try question("card-run-orch"))!
        XCTAssertEqual(orch.kind, .run)
        XCTAssertEqual(orch.card.run?.runsHere, true)
        XCTAssertNil(orch.card.run?.whyNotHere)
        XCTAssertEqual(ReviewStackRules.okOutcome(orch, picked: nil), .allowed)
        for name in ["card-run-other", "card-run-copy", "card-run-login"] {
            let item = ReviewStackRules.item(for: try question(name))!
            XCTAssertEqual(item.card.run?.runsHere, false, name)
            XCTAssertEqual(ReviewStackRules.okOutcome(item, picked: nil), .atComputer, name)
            let why = try XCTUnwrap(item.card.run?.whyNotHere, name)
            XCTAssertFalse(why.contains("\n"), name)
        }
    }
    func testAnswersAreOrchsOwnWords() throws {
        let item = ReviewStackRules.item(for: try question("card-run-orch"))!
        let ok = try XCTUnwrap(ReviewStackRules.verdict(item, .ok)), no = try XCTUnwrap(ReviewStackRules.verdict(item, .no))
        XCTAssertEqual(ReviewStackRules.summary(item, verdict: ok), "I ran it")
        XCTAssertEqual(ReviewStackRules.summary(item, verdict: no), "Leave it off for now")
        XCTAssertEqual(ReviewStackRules.countsText([item]), "1 command")
    }
    @MainActor func testOkOnARunCardThePhoneMayNotRunIsNeverQueued() throws {
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let box = Outbox(directory: dir, phone: "ph_iphone0001")
        let other = try question("card-run-other"), digest = other.message.body.digest!
        XCTAssertThrowsError(try box.enqueueAnswer(question: other, answer: "I ran it", verdict: ReviewVerdict(verdict: .ok, digest: digest))) {
            XCTAssertEqual($0 as? Outbox.VerdictProblem, .invalid)
        }
        XCTAssertNoThrow(try box.enqueueAnswer(question: other, answer: "Not now", verdict: ReviewVerdict(verdict: .no, digest: digest)))
        let orch = try question("card-run-orch")
        XCTAssertNoThrow(try box.enqueueAnswer(question: orch, answer: "I ran it", verdict: ReviewVerdict(verdict: .ok, digest: orch.message.body.digest!)))
    }
    func testAnOrchCommandThePhoneMayNotRunShowsWhy() throws {
        let run = CardRun(command: "orch config set workflow.reviewer_look on", cls: .orch, phone: false)
        XCTAssertFalse(run.runsHere)
        XCTAssertEqual(run.whyNotHere, "Run this one at your computer.")
        let item = ReviewStackRules.item(for: cardQ("m_rx", ReviewCard(kind: .run, title: "T", then: "x", run: run, noLabel: "Not now")))!
        XCTAssertEqual(ReviewStackRules.okOutcome(item, picked: nil), .atComputer)
    }
    @MainActor func testOutboxRefusesOkWithoutTheDecoderOnAPhoneFlagOnAnotherClass() throws {
        // built in code (the decoder would refuse it): phone true on a command that is not orch's own never runs here
        let run = CardRun(command: "brew install gh", cls: .other, phone: true)
        XCTAssertFalse(run.runsHere); XCTAssertFalse(run.isValid)
        let q = cardQ("m_ry", ReviewCard(kind: .run, title: "T", then: "x", run: run, noLabel: "Not now"))
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let box = Outbox(directory: dir, phone: "ph_iphone0001")
        XCTAssertThrowsError(try box.enqueueAnswer(question: q, answer: "I ran it", verdict: ReviewVerdict(verdict: .ok, digest: q.message.body.digest!)))
    }
    func testABrokenRunCardIsNotAnsweredAsAPlainQuestion() throws {
        // the card is dropped on decode; a question without options is not a stack card, so no ok can be sent from the stack
        let json = #"{"schema":"orch.msg/1","id":"m_z","from":"ws_p","to":"phones","type":"question","created_at":"2026-11-15T09:00:00Z","body":{"question_id":"q1","text":"T","options":[],"digest":"\#(String(repeating: "b", count: 64))","card":{"kind":"run","title":"t","then":"x","run":{"command":"rm x; id","class":"orch","phone":true},"no_label":"Not now"}}}"#
        let m = try JSONCoding.decoder.decode(QuestionMessage.self, from: Data(json.utf8))
        XCTAssertNil(m.body.card)
        XCTAssertNil(ReviewStackRules.kind(of: Question(message: m, workspaceName: "P")))
    }
}
