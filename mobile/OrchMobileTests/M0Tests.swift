import XCTest
import CoreLocation
@testable import OrchMobile

private func tmpDir() -> URL {
    let d = FileManager.default.temporaryDirectory.appendingPathComponent("m0-" + UUID().uuidString)
    try! FileManager.default.createDirectory(at: d, withIntermediateDirectories: true); return d
}
private func file(_ dir: URL, _ name: String, bytes: Int = 10) -> URL {
    let u = dir.appendingPathComponent(name); try! Data(repeating: 7, count: bytes).write(to: u); return u
}
private func vectors() throws -> [String: Any] {
    // The vector file is copied next to the examples at build time (Fixtures/phone-v3-v1.json).
    let url = Bundle(for: BundleToken.self).url(forResource: "phone-v3-v1", withExtension: "json")!
    return try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
}

// MARK: Contract vectors and fixtures

final class V3ContractTests: XCTestCase {
    func testSendVectorsDecodeAndValidate() throws {
        let v = try vectors()
        for c in v["send"] as! [[String: Any]] {
            let name = c["name"] as! String, ok = c["ok"] as! Bool
            let data = try JSONSerialization.data(withJSONObject: c["request"]!)
            guard let r = try? JSONCoding.decoder.decode(SendRequest.self, from: data) else { XCTAssertFalse(ok, "\(name) must decode"); continue }
            if ok { XCTAssertNoThrow(try r.validate(), name) } else { XCTAssertThrowsError(try r.validate(), name) }
        }
    }
    func testSendRequestEncodesLikeTheVectorBuiltBody() throws {
        let v = try vectors()
        for c in (v["send"] as! [[String: Any]]) where (c["ok"] as! Bool) {
            let r = try JSONCoding.decoder.decode(SendRequest.self, from: JSONSerialization.data(withJSONObject: c["request"]!))
            let enc = try JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(r)) as! NSDictionary
            let want = (c["request"] as! [String: Any]).filter { !($0.value is NSNull) }      // null ticket/reply_to = left out
            XCTAssertEqual(enc, want as NSDictionary, c["name"] as! String)
        }
    }
    func testBuiltMessagesDecodeAsTexts() throws {
        let v = try vectors()
        for c in (v["send"] as! [[String: Any]]) where (c["ok"] as! Bool) {
            var m = c["built"] as! [String: Any]
            m["id"] = "m_abcdefghij012345"; m["created_at"] = "2026-11-06T10:00:00Z"
            let tm = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: m))
            XCTAssertNotNil(tm.body.clientId, c["name"] as! String)
        }
    }
    func testArtifactIdAndRevDecode() throws {
        let json = #"{"kind":"pr","id":"a_9b27f17f5357","rev":"abc123","title":"Fix","at":"2026-11-06T10:00:00Z","url":"https://github.com/a/b/pull/1","status":"open"}"#
        let a = try JSONCoding.decoder.decode(TicketSnapshot.Attachment.self, from: Data(json.utf8))
        XCTAssertEqual(a.artifactId, "a_9b27f17f5357"); XCTAssertEqual(a.rev, "abc123"); XCTAssertEqual(a.id, "a_9b27f17f5357"); XCTAssertFalse(a.isBlob)
    }
    func testSettingsPatchValidity() throws {
        let v = try vectors()
        for c in v["settings_patch"] as! [[String: Any]] {
            guard let p = try? JSONCoding.decoder.decode(SettingsPatch.self, from: JSONSerialization.data(withJSONObject: c["request"]!)) else { XCTAssertFalse(c["ok"] as! Bool, c["name"] as! String); continue }
            XCTAssertEqual(p.isValid, c["ok"] as! Bool, c["name"] as! String)
        }
    }
    func testSpokenTextVectors() throws {
        let v = try vectors()
        for c in v["speech_text"] as! [[String: Any]] {
            let b = c["body"] as! [String: Any], speak = b["speak"] as? [String: Any]
            XCTAssertEqual(SpokenText.make(text: b["text"] as! String, summary: speak?["summary"] as? String), c["spoken"] as? String, c["name"] as! String)
        }
    }
    func testExamplesDecode() throws {
        _ = try JSONCoding.decoder.decode(ListResponse<PhoneMessage>.self, from: Example.find("GET", "/v1/phone/messages").responseData)
        let ws = try JSONCoding.decoder.decode(ListResponse<Workspace>.self, from: Example.find("GET", "/v1/phone/workspaces").responseData)
        XCTAssertFalse(ws.items.isEmpty)
    }
    func testQuestionPreviewsAndScope() {
        let q = Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_x", from: "ws_a", to: "phones", type: "question", createdAt: "2026-11-06T10:00:00Z", ticket: nil,
                                                  body: QuestionBody(questionId: "q1", title: nil, text: "Send?", options: ["Once", "Always", "No"], recommended: nil,
                                                                     previews: ["Once": "a_9b27f17f5357"], scope: "sending to anna@pilatus.ch")), workspaceName: "A")
        XCTAssertEqual(q.label("Always"), "Always allow sending to anna@pilatus.ch"); XCTAssertEqual(q.previewId(for: "Once"), "a_9b27f17f5357"); XCTAssertNil(q.previewId(for: "No"))
    }
    func testMuteWire() {
        XCTAssertNil(Mute.off.wire); XCTAssertEqual(Mute.forever.wire, "forever")
        XCTAssertEqual(Mute.until(Date(timeIntervalSince1970: 0)).wire, "1970-01-01T00:00:00Z")
        var w = Workspace(id: "ws_a", name: "A", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0)
        XCTAssertFalse(w.isMuted()); w.mutedUntil = "forever"; XCTAssertTrue(w.isMuted()); w.mutedUntil = "2000-01-01T00:00:00Z"; XCTAssertFalse(w.isMuted())
    }
}

// MARK: Client against the stub

final class V3ClientTests: XCTestCase {
    private func client() -> URLSessionRelayClient {
        URLSessionRelayClient(base: URL(string: "https://relay.test")!, credentials: Credentials(relay: URL(string: "https://relay.test")!, phoneId: "ph_a", token: "orn_x", phoneName: "T"), session: StubProtocol.session())
    }
    func testSendPostsV3Body() async throws {
        StubProtocol.handler = { _ in (201, Data(#"{"id":"m_abcdefghij012345","client_id":"6f1c2a9e-3b7d-4c8e-9a10-2b3c4d5e6f70"}"#.utf8)) }
        let r = try await client().send(SendRequest(to: "ws_pilatus001", clientId: "6f1c2a9e-3b7d-4c8e-9a10-2b3c4d5e6f70", text: "hi", general: true))
        XCTAssertEqual(r.id, "m_abcdefghij012345"); XCTAssertNil(r.duplicate)
        let req = StubProtocol.seen[0]; XCTAssertEqual(req.url?.path, "/v1/phone/send")
        let body = try JSONSerialization.jsonObject(with: StubProtocol.seenBodies[0]) as! [String: Any]
        XCTAssertEqual(body["client_id"] as? String, "6f1c2a9e-3b7d-4c8e-9a10-2b3c4d5e6f70"); XCTAssertEqual(body["general"] as? Bool, true); XCTAssertNil(body["ticket"])
    }
    func testDuplicateSendIs200Duplicate() async throws {
        StubProtocol.handler = { _ in (200, Data(#"{"id":"m_abcdefghij012345","client_id":"6f1c2a9e-3b7d-4c8e-9a10-2b3c4d5e6f70","duplicate":true}"#.utf8)) }
        let r = try await client().send(SendRequest(to: "ws_pilatus001", clientId: "6f1c2a9e-3b7d-4c8e-9a10-2b3c4d5e6f70", text: "hi"))
        XCTAssertEqual(r.duplicate, true)
    }
    func testMessagesPaginationQuery() async throws {
        StubProtocol.handler = { _ in (200, Data(#"{"items":[],"next":null}"#.utf8)) }
        _ = try await client().messages(after: "m_abc", limit: 30)
        XCTAssertEqual(StubProtocol.seen[0].url?.query, "after=m_abc&limit=30")
    }
    func testUploadBlobSendsFileBytes() async throws {
        StubProtocol.handler = { _ in (201, Data(#"{"blob_id":"b_ph0ne1mage000001","size":10,"sha256":"00"}"#.utf8)) }
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let b = try await client().uploadBlob(file: file(dir, "p.jpg"), contentType: "image/jpeg")
        XCTAssertEqual(b.blobId, "b_ph0ne1mage000001")
        XCTAssertEqual(StubProtocol.seen[0].value(forHTTPHeaderField: "Content-Type"), "image/jpeg"); XCTAssertEqual(StubProtocol.seen[0].httpMethod, "POST")
        XCTAssertEqual(StubProtocol.seen[0].url?.path, "/v1/phone/blobs")
    }
    func testSettingsAndMuteAndRedeem() async throws {
        let c = client()
        StubProtocol.handler = { _ in (200, Data(#"{"speak":"auto","swiss_german":false,"tts_cap_usd":10,"tts_used_usd_month":1.5}"#.utf8)) }
        let s = try await c.settings(); XCTAssertEqual(s.ttsLeftUsd, 8.5)
        _ = try await c.updateSettings(SettingsPatch(speak: .never))
        let body = try JSONSerialization.jsonObject(with: StubProtocol.seenBodies.last!) as! [String: Any]
        XCTAssertEqual(body["speak"] as? String, "never"); XCTAssertNil(body["swiss_german"])
        StubProtocol.handler = { _ in (200, Data(#"{"id":"ws_pilatus001","name":"P","description":"","tags":[],"online":true,"last_seen":null,"open_questions":0,"muted_until":null}"#.utf8)) }
        _ = try await c.setMute(workspace: "ws_pilatus001", mute: .off)
        let mb = try JSONSerialization.jsonObject(with: StubProtocol.seenBodies.last!) as! [String: Any]
        XCTAssertTrue(mb.keys.contains("muted_until")); XCTAssertTrue(mb["muted_until"] is NSNull, "null is sent to unmute")
        StubProtocol.handler = { _ in (410, Data(#"{"error":"gone","message":"used"}"#.utf8)) }
        do { _ = try await c.redeem(code: "pc_x"); XCTFail() } catch let RelayError.api(st, code, _) { XCTAssertEqual(st, 410); XCTAssertEqual(code, "gone") }
    }
    func testSpeechErrorsAndBytes() async throws {
        let c = client()
        StubProtocol.handler = { _ in (200, Data("mp3".utf8)) }
        let d = try await c.speech(messageId: "m_abcdefghij012345", lang: "de"); XCTAssertEqual(d, Data("mp3".utf8))
        XCTAssertEqual(StubProtocol.seen.last?.url?.query, "lang=de"); XCTAssertEqual(StubProtocol.seen.last?.value(forHTTPHeaderField: "Accept"), "audio/mpeg")
        StubProtocol.handler = { _ in (402, Data(#"{"error":"tts_cap_reached","message":"cap"}"#.utf8)) }
        do { _ = try await c.speech(messageId: "m_abcdefghij012345", lang: nil); XCTFail() } catch let e { XCTAssertTrue(SpeechPlayer.shouldUsePhoneVoice(e)) }
        StubProtocol.handler = { _ in (404, Data(#"{"error":"not_found","message":"x"}"#.utf8)) }
        do { _ = try await c.speech(messageId: "m_abcdefghij012345", lang: nil); XCTFail() } catch let e { XCTAssertFalse(SpeechPlayer.shouldUsePhoneVoice(e)) }
    }
}

// MARK: Outbox

@MainActor
final class OutboxTests: XCTestCase {
    var dir: URL!, scratch: URL!
    override func setUp() async throws { dir = tmpDir(); scratch = tmpDir(); UserDefaults.standard.removeObject(forKey: "mockFail") }
    override func tearDown() async throws { try? FileManager.default.removeItem(at: dir); try? FileManager.default.removeItem(at: scratch) }

    func testQueuedThenSentThenReconciled() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let item = try ob.enqueue(MessageDraft(text: "  hello  "), to: .general(workspace: MockRelay.pilatus))
        XCTAssertEqual(item.text, "hello"); XCTAssertTrue(item.general); XCTAssertTrue(item.isWaiting)
        let ev = await ob.flush(using: relay)
        guard case .sent(let cid, _, let dup) = ev.first else { return XCTFail("\(ev)") }
        XCTAssertEqual(cid, item.clientId); XCTAssertFalse(dup)
        XCTAssertNotNil(ob.item(clientId: cid)?.sentMessageId, "stays until the relay lists it (a restart in between must not resend)")
        let list = try await relay.messages(after: nil, limit: nil).items
        ob.reconcile(with: list)
        XCTAssertTrue(ob.items.isEmpty)
        let sent = await relay.requests; XCTAssertEqual(sent.count, 1); XCTAssertEqual(sent[0].general, true); XCTAssertEqual(sent[0].clientId, item.clientId)
    }
    func testOfflineKeepsOrderAndRetriesWithSameClientId() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        await relay.setOffline(true)
        let a = try ob.enqueue(MessageDraft(text: "one"), to: .topic(workspace: MockRelay.pilatus, ticket: "t_q3sum1"))
        let b = try ob.enqueue(MessageDraft(text: "two"), to: .topic(workspace: MockRelay.pilatus, ticket: "t_q3sum1"))
        var ev = await ob.flush(using: relay); XCTAssertEqual(ev, [.offline]); XCTAssertEqual(ob.items.count, 2)
        await relay.setOffline(false)
        ev = await ob.flush(using: relay)
        XCTAssertEqual(ev.compactMap { if case .sent(let c, _, _) = $0 { c } else { nil } }, [a.clientId, b.clientId], "oldest first")
        let sent = await relay.requests; XCTAssertEqual(sent.map(\.text), ["one", "two"])
    }
    func testRetryAfterLostResponseIsADuplicateNotASecondMessage() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let item = try ob.enqueue(MessageDraft(text: "once"), to: .general(workspace: MockRelay.pilatus))
        _ = try await relay.send(try Outbox.request(for: item))      // the relay got it, the phone never heard back
        let ev = await ob.flush(using: relay)
        guard case .sent(_, _, let dup) = ev.first else { return XCTFail() }
        XCTAssertTrue(dup)
        let n = try await relay.messages(after: nil, limit: nil).items.filter { $0.fromPhone && $0.message.body.text == "once" }.count; XCTAssertEqual(n, 1)
    }
    func testSurvivesRestartAndNeverUploadsTwice() async throws {
        let relay = MockRelay(latency: .zero)
        var ob: Outbox? = Outbox(directory: dir, phone: "ph_iphone0001")
        let img = file(scratch, "IMG.jpg", bytes: 2000)
        let item = try ob!.enqueue(MessageDraft(text: "see", files: [DraftFile(url: img, kind: .image, name: "IMG.jpg", mime: "image/jpeg")]), to: .newTopic(workspace: MockRelay.pilatus))
        try? FileManager.default.removeItem(at: img)                                  // the caller's copy is gone: the outbox has its own
        ob = nil
        let again = Outbox(directory: dir, phone: "ph_iphone0001")
        XCTAssertEqual(again.items.count, 1); XCTAssertTrue(again.items[0].isNewTopic)
        let ev = await again.flush(using: relay)
        guard case .sent = ev.first else { return XCTFail("\(ev)") }
        let up = await relay.uploads; XCTAssertEqual(up.count, 1); XCTAssertEqual(up.values.first?.count, 2000)
        let req = await relay.requests[0]
        XCTAssertEqual(req.attachments?.first?.blobId, again.item(clientId: item.clientId)?.files[0].blobId); XCTAssertEqual(req.attachments?.first?.size, 2000)
    }
    func testUploadedFileIsNotUploadedAgainOnRetry() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        _ = try ob.enqueue(MessageDraft(files: [DraftFile(url: file(scratch, "a.pdf", bytes: 50), kind: .file, name: "a.pdf", mime: "application/pdf")]), to: .general(workspace: MockRelay.pilatus))
        await relay.setOffline(false)
        // first pass: upload works, send fails (workspace unreachable for this phone) -> marked failed; retry must reuse the blob
        _ = await ob.flush(using: relay)
        let n1 = await relay.uploads.count
        ob.items.first.map { ob.retry($0.clientId) }
        _ = await ob.flush(using: relay)
        let n2 = await relay.uploads.count
        XCTAssertEqual(n1, 1); XCTAssertEqual(n2, 1)
    }
    func testRefusalMarksFailedAndNextItemStillGoes() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let bad = try ob.enqueue(MessageDraft(text: "x"), to: .general(workspace: "ws_nope000001"))
        let good = try ob.enqueue(MessageDraft(text: "y"), to: .general(workspace: MockRelay.pilatus))
        let ev = await ob.flush(using: relay)
        XCTAssertTrue(ev.contains { if case .failed(let c, 403, _) = $0 { c == bad.clientId } else { false } })
        XCTAssertNotNil(ob.item(clientId: good.clientId)?.sentMessageId)
        XCTAssertNotNil(ob.item(clientId: bad.clientId)?.failure)
        let again = await ob.flush(using: relay); XCTAssertTrue(again.isEmpty, "a failed item is not retried by itself")
        ob.discard(bad.clientId); XCTAssertNil(ob.item(clientId: bad.clientId))
    }
    func testUpload408ThenSuccessKeepsClientIdAndNeverFailsForGood() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let item = try ob.enqueue(MessageDraft(files: [DraftFile(url: file(scratch, "a.pdf", bytes: 50), kind: .file, name: "a.pdf", mime: "application/pdf")]), to: .general(workspace: MockRelay.pilatus))
        await relay.queueUploadFailures([408])
        let t0 = Date()
        var ev = await ob.flush(using: relay, now: t0)
        XCTAssertEqual(ev, [Outbox.Event.throttled(clientId: item.clientId, status: 408)])
        XCTAssertNil(ob.item(clientId: item.clientId)?.failure, "408 is never a permanent failure"); XCTAssertTrue(ob.item(clientId: item.clientId)!.isWaiting)
        ev = await ob.flush(using: relay, now: t0.addingTimeInterval(5)); XCTAssertTrue(ev.isEmpty, "backing off: not tried on every refresh")
        let calls1 = await relay.uploadCalls; XCTAssertEqual(calls1, 1)
        ev = await ob.flush(using: relay, now: t0.addingTimeInterval(31))
        guard case .sent(let cid, _, _) = ev.first else { return XCTFail("\(ev)") }
        XCTAssertEqual(cid, item.clientId)
        let req = await relay.requests; XCTAssertEqual(req.count, 1); XCTAssertEqual(req[0].clientId, item.clientId); XCTAssertNotNil(req[0].attachments?.first?.blobId)
        XCTAssertNil(ob.item(clientId: item.clientId)?.retryAfter)
    }
    func testSend429BacksOffAndDoublesUpToFiveMinutes() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let item = try ob.enqueue(MessageDraft(text: "x"), to: .general(workspace: MockRelay.pilatus))
        await relay.queueSendFailures([429, 503, 429, 429, 429, 429, 429])
        var now = Date(timeIntervalSince1970: Date().timeIntervalSince1970.rounded(.down))   // whole seconds: the stored time has none
        var waits: [TimeInterval] = []
        for _ in 0..<7 {
            let ev = await ob.flush(using: relay, now: now)
            XCTAssertEqual(ev.count, 1); if case .throttled = ev[0] {} else { XCTFail("\(ev)") }
            let at = ISO8601DateFormatter().date(from: ob.item(clientId: item.clientId)!.retryAfter!)!
            waits.append(at.timeIntervalSince(now).rounded()); now = at.addingTimeInterval(1)
        }
        XCTAssertEqual(waits, [30, 60, 120, 240, 300, 300, 300])
        let ev = await ob.flush(using: relay, now: now); guard case .sent = ev.first else { return XCTFail("\(ev)") }
    }
    func testRetryAfterABlobRefusalUploadsAgain() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let item = try ob.enqueue(MessageDraft(files: [DraftFile(url: file(scratch, "a.pdf", bytes: 50), kind: .file, name: "a.pdf", mime: "application/pdf")]), to: .general(workspace: MockRelay.pilatus))
        await relay.queueSendFailures([404])                   // the relay lost the upload
        var ev = await ob.flush(using: relay)
        XCTAssertTrue(ev.contains { if case .failed(_, 404, _) = $0 { true } else { false } })
        XCTAssertNotNil(ob.item(clientId: item.clientId)?.files[0].blobId)
        ob.retry(item.clientId)
        XCTAssertNil(ob.item(clientId: item.clientId)?.files[0].blobId, "the file goes up again")
        ev = await ob.flush(using: relay); guard case .sent = ev.first else { return XCTFail("\(ev)") }
        let n = await relay.uploadCalls; XCTAssertEqual(n, 2)
    }
    func testCopiedFilesAreProtectedLikeTheIndex() throws {
        let ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let item = try ob.enqueue(MessageDraft(files: [DraftFile(url: file(scratch, "a.pdf", bytes: 5), kind: .file, name: "a.pdf", mime: "application/pdf")]), to: .general(workspace: MockRelay.pilatus))
        let u = ob.fileURL(item, ob.item(clientId: item.clientId)!.files[0])
        XCTAssertTrue(FileManager.default.fileExists(atPath: u.path)); XCTAssertNil(ob.lastSaveError)
    }
    func testOverlappingFlushesSendOnce() async throws {
        let relay = MockRelay(latency: .milliseconds(20)), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        _ = try ob.enqueue(MessageDraft(text: "solo"), to: .general(workspace: MockRelay.pilatus))
        async let a = ob.flush(using: relay); async let b = ob.flush(using: relay); async let c = ob.flush(using: relay)
        _ = await (a, b, c)
        let n = await relay.requests.count; XCTAssertEqual(n, 1)
    }
    func testInvalidDraftsAreRefusedAndLeaveNothingOnDisk() throws {
        let ob = Outbox(directory: dir, phone: "ph_iphone0001")
        XCTAssertThrowsError(try ob.enqueue(MessageDraft(text: "   "), to: .general(workspace: "ws_pilatus001")))
        XCTAssertThrowsError(try ob.enqueue(MessageDraft(feedback: DraftFeedback(artifactId: "a_9b27f17f5357", artifactRev: "r1", verdict: .approve)), to: .general(workspace: "ws_pilatus001")))   // feedback needs a topic
        XCTAssertThrowsError(try ob.enqueue(MessageDraft(feedback: DraftFeedback(artifactId: "a_9b27f17f5357", artifactRev: "r1", verdict: .changes)), to: .topic(workspace: "ws_pilatus001", ticket: "t_q3sum1")))   // no pins
        XCTAssertNoThrow(try ob.enqueue(MessageDraft(feedback: DraftFeedback(artifactId: "a_9b27f17f5357", artifactRev: "r1", verdict: .approve)), to: .topic(workspace: "ws_pilatus001", ticket: "t_q3sum1")))
        XCTAssertEqual(ob.items.count, 1)
        XCTAssertEqual((try? FileManager.default.contentsOfDirectory(atPath: dir.path))?.filter { $0 != "outbox.json" }.count, 1)
    }
    func testVoiceFeedbackPinsAndLocationUploadAndSend() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let fb = DraftFeedback(artifactId: "a_9b27f17f5357", artifactRev: "r1", verdict: .changes,
                               pins: [DraftPin(n: 1, anchor: Anchor(type: .image, x: 0.2, y: 0.4), voiceFile: file(scratch, "p.m4a", bytes: 30), transcript: "bigger")])
        _ = try ob.enqueue(MessageDraft(feedback: fb), to: .topic(workspace: MockRelay.pilatus, ticket: "t_q3sum1"))
        _ = try ob.enqueue(MessageDraft(voice: DraftVoice(url: file(scratch, "v.m4a", bytes: 40), duration: 3, transcript: "hallo", lang: "de-CH", langSource: .setting)), to: .general(workspace: MockRelay.pilatus))
        _ = try ob.enqueue(MessageDraft(location: LocationShare(lat: 47.05, lon: 8.3, label: "Luzern", accuracyM: 12)), to: .general(workspace: MockRelay.pilatus))
        let ev = await ob.flush(using: relay)
        XCTAssertEqual(ev.filter { if case .sent = $0 { true } else { false } }.count, 3, "\(ev)")
        let reqs = await relay.requests
        XCTAssertNotNil(reqs[0].feedback?.pins[0].voiceBlobId); XCTAssertEqual(reqs[1].voice?.langSource, .setting); XCTAssertEqual(reqs[2].location?.accuracyM, 12)
    }
    func testAnswersUseOneClientIdAndLoseToAnotherPhone() async throws {
        let relay = MockRelay(latency: .zero), ob = Outbox(directory: dir, phone: "ph_iphone0001")
        let q = try await relay.questions()[0]
        let a1 = ob.enqueueAnswer(question: q, answer: "DATE"), a2 = ob.enqueueAnswer(question: q, answer: "TIMESTAMP")
        XCTAssertEqual(a1.clientId, a2.clientId, "one queued answer per question")
        let ev = await ob.flush(using: relay)
        XCTAssertEqual(ev, [.answered(clientId: a1.clientId, questionMessageId: q.id, answer: "DATE")]); XCTAssertTrue(ob.items.isEmpty)
        // another phone got there first
        let q2 = try await relay.questions()[0]
        _ = try await relay.answer(AnswerRequest(questionMessageId: q2.id, answer: "No", clientId: UUID().uuidString.lowercased()))
        _ = ob.enqueueAnswer(question: q2, answer: "Yes")
        let ev2 = await ob.flush(using: relay)
        guard case .answerTaken = ev2.first else { return XCTFail("\(ev2)") }
    }
    func testAnotherPhonesItemsAreDroppedAndWipeClears() throws {
        let ob = Outbox(directory: dir, phone: "ph_a")
        _ = try ob.enqueue(MessageDraft(text: "mine"), to: .general(workspace: "ws_pilatus001"))
        let other = Outbox(directory: dir, phone: "ph_b"); XCTAssertTrue(other.items.isEmpty)
        let back = Outbox(directory: dir, phone: "ph_a"); XCTAssertTrue(back.items.isEmpty, "never sent under another phone; dropped")
        _ = try other.enqueue(MessageDraft(text: "b"), to: .general(workspace: "ws_pilatus001")); other.wipe()
        XCTAssertTrue(Outbox(directory: dir, phone: "ph_b").items.isEmpty)
    }
    func testFileLimits() throws {
        let big = scratch.appendingPathComponent("big.bin")
        FileManager.default.createFile(atPath: big.path, contents: nil)
        let h = try FileHandle(forWritingTo: big); try h.truncate(atOffset: UInt64(SendRequest.maxBlobBytes + 1)); try h.close()
        XCTAssertThrowsError(try MediaPrep.checkFile(at: big))
        XCTAssertThrowsError(try MediaPrep.checkFile(at: file(scratch, "empty", bytes: 0)))
        XCTAssertEqual(try MediaPrep.checkFile(at: file(scratch, "ok", bytes: 5)), 5)
        XCTAssertFalse(Outbox.safeFileName("../.hidden/evil.pdf").contains("/")); XCTAssertFalse(Outbox.safeFileName("..x").hasPrefix("."))
    }
}

// MARK: Conversations

final class ConversationTests: XCTestCase {
    private func text(_ id: String, from: String, to: String, at: String, ticket: String? = nil, body: TextBody, replyTo: String? = nil, delivered: String? = nil, cid: String? = nil) -> PhoneMessage {
        PhoneMessage(message: TextMessage(id: id, from: from, to: to, type: "text", createdAt: at, ticket: ticket, body: body, replyTo: replyTo), workspaceName: "Pilatus", deliveredAt: delivered, clientId: cid)
    }
    private let ws = "ws_pilatus001", me = "ph_iphone0001"

    func testGeneralVersusTopicsVersusStarting() {
        var d = ConversationInputs(workspaces: [Workspace(id: ws, name: "Pilatus", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0)])
        d.messages = [
            text("m_g", from: me, to: ws, at: "2026-11-06T10:00:00Z", body: TextBody(text: "general", clientId: "c1", general: true), cid: "c1"),
            text("m_t", from: me, to: ws, at: "2026-11-06T10:01:00Z", ticket: "t_q3sum1", body: TextBody(text: "in topic", clientId: "c2"), cid: "c2"),
            text("m_n", from: me, to: ws, at: "2026-11-06T10:02:00Z", body: TextBody(text: "new topic", clientId: "c3"), cid: "c3"),
            text("m_w", from: ws, to: me, at: "2026-11-06T10:03:00Z", body: TextBody(text: "workspace general", general: true)),
        ]
        XCTAssertEqual(ConversationBuilder.items(.general(workspace: ws), d).map(\.id), ["m_g", "m_w"])
        XCTAssertEqual(ConversationBuilder.items(.topic(workspace: ws, ticket: "t_q3sum1"), d).map(\.id), ["m_t"])
        let s = ConversationBuilder.topics(workspace: ws, d, read: ReadState())
        XCTAssertEqual(s.count, 1); XCTAssertTrue(s[0].isStarting); XCTAssertEqual(s[0].lastLine, "Starting topic…")
        // the ack names the ticket -> the text moves into that topic
        d.messages.append(text("m_ack", from: ws, to: me, at: "2026-11-06T10:02:30Z", ticket: "t_new0001", body: TextBody(text: "Got it", update: TextUpdate(kind: "ack", title: "New")), replyTo: "m_n"))
        XCTAssertEqual(ConversationBuilder.items(.topic(workspace: ws, ticket: "t_new0001"), d).map(\.id), ["m_n"])
        XCTAssertEqual(ConversationBuilder.resolve(.starting(workspace: ws, id: "c3"), d), .topic(workspace: ws, ticket: "t_new0001"))
        XCTAssertTrue(ConversationBuilder.topics(workspace: ws, d, read: ReadState()).allSatisfy { !$0.isStarting })
    }
    func testReceiptsQueuedSentDeliveredStarted() {
        var d = ConversationInputs()
        let o = OutboxItem(clientId: "c0", phone: me, kind: .send, workspace: ws, createdAt: "2026-11-06T09:59:00Z", general: true, text: "queued")
        d.outbox = [o]
        XCTAssertEqual(ConversationBuilder.items(.general(workspace: ws), d)[0].receipt, .queued)
        d.outbox[0].failure = "no"; XCTAssertEqual(ConversationBuilder.items(.general(workspace: ws), d)[0].receipt, .failed("no"))
        d.outbox = []
        d.messages = [text("m_a", from: me, to: ws, at: "2026-11-06T10:00:00Z", body: TextBody(text: "a", clientId: "c1", general: true), cid: "c1")]
        XCTAssertEqual(ConversationBuilder.items(.general(workspace: ws), d)[0].receipt, .sent)
        d.messages[0].deliveredAt = "2026-11-06T10:00:05Z"; XCTAssertEqual(ConversationBuilder.items(.general(workspace: ws), d)[0].receipt, .delivered)
        d.messages.append(text("m_r", from: ws, to: me, at: "2026-11-06T10:00:10Z", body: TextBody(text: "Looking", update: TextUpdate(kind: "working"), general: true), replyTo: "m_a"))
        let items = ConversationBuilder.items(.general(workspace: ws), d)
        XCTAssertEqual(items.count, 1, "a General receipt is ticks, not a bubble"); XCTAssertEqual(items[0].receipt, .started); XCTAssertEqual(items[0].receipt?.ticks, 2)
    }
    func testSentItemInOutboxIsNotShownTwice() {
        var d = ConversationInputs()
        d.outbox = [OutboxItem(clientId: "c1", phone: me, kind: .send, workspace: ws, createdAt: "2026-11-06T10:00:00Z", general: true, text: "x", sentMessageId: "m_a")]
        d.messages = [text("m_a", from: me, to: ws, at: "2026-11-06T10:00:01Z", body: TextBody(text: "x", clientId: "c1", general: true), cid: "c1")]
        XCTAssertEqual(ConversationBuilder.items(.general(workspace: ws), d).count, 1)
    }
    func testTopicStatusAndUnreadAndPlayButton() {
        let upd = TicketUpdate(id: "m_u", workspace: ws, workspaceName: "P", ticket: "t_q3sum1", kind: "failure", title: "Q3", text: "broke", replyTo: nil, at: "2026-11-06T10:05:00Z")
        var d = ConversationInputs(workspaces: [Workspace(id: ws, name: "P", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0)])
        d.tickets = TicketBuilder.build(updates: [upd], questions: [], answers: [:])
        d.messages = [text("m_f", from: ws, to: me, at: "2026-11-06T10:05:00Z", ticket: "t_q3sum1", body: TextBody(text: "broke", update: TextUpdate(kind: "failure"), speak: SpeakHint(lang: "en")))]
        let t = ConversationBuilder.topics(workspace: ws, d, read: ReadState())
        XCTAssertEqual(t[0].status, .didntWork); XCTAssertEqual(t[0].status.label, "Didn't work"); XCTAssertEqual(t[0].unread, 1)
        XCTAssertTrue(ConversationBuilder.items(t[0].id, d)[0].canPlay)
        d.speak = .never; XCTAssertFalse(ConversationBuilder.items(t[0].id, d)[0].canPlay)
        var r = ReadState(); r.markRead(ReadState.key(t[0].id), upTo: "2026-11-06T10:05:00Z")
        XCTAssertEqual(ConversationBuilder.topics(workspace: ws, d, read: r)[0].unread, 0)
        XCTAssertEqual(TopicStatus.allCases.map(\.label), ["Working", "Waiting", "Review", "Backlog", "Done", "Stopped", "Didn't work"])
    }
    func testLanguageLabelOnlyWhenDifferent() {
        XCTAssertNil(LanguageLabel.label(memo: "de-CH", conversation: "de-CH")); XCTAssertEqual(LanguageLabel.label(memo: "en", conversation: "de-CH"), "EN")
        func memo(_ l: String) -> ConvItem { ConvItem(id: l + UUID().uuidString, at: "x", side: .me, voice: VoiceMemo(blobId: "b", transcript: "t", lang: l, langSource: .detected)) }
        XCTAssertEqual(LanguageLabel.conversationLanguage([memo("de"), memo("de"), memo("en")]), "de")
        XCTAssertEqual(LanguageLabel.conversationLanguage([], fallback: "fr"), "fr")
    }
}

// MARK: Presence, media, speech, voice

final class SmallPartsTests: XCTestCase {
    func testPresence() {
        var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "UTC")!
        let now = ISO8601DateFormatter().date(from: "2026-11-06T15:00:00Z")!
        XCTAssertEqual(Presence.of(lastSeen: "2026-11-06T14:56:00Z", now: now), .online)
        XCTAssertEqual(Presence.of(lastSeen: "2026-11-06T14:54:00Z", now: now).text(now: now, calendar: cal), "Last seen 14:54")
        XCTAssertEqual(Presence.of(lastSeen: "2026-11-05T18:40:00Z", now: now).text(now: now, calendar: cal), "Last seen yesterday 18:40")
        XCTAssertEqual(Presence.of(lastSeen: "2026-11-03T08:00:00Z", now: now).text(now: now, calendar: cal), "Last seen 3 Nov")
        XCTAssertEqual(Presence.of(lastSeen: nil, now: now).text(), "Offline"); XCTAssertEqual(Presence.online.text(), "Online")
    }
    func testPhotoIsJpegBoundedAndStripped() throws {
        let r = UIGraphicsImageRenderer(size: CGSize(width: 3000, height: 1500), format: { let f = UIGraphicsImageRendererFormat(); f.scale = 1; return f }())
        let png = r.pngData { c in UIColor.red.setFill(); c.fill(CGRect(x: 0, y: 0, width: 3000, height: 1500)) }
        // a source with GPS metadata
        let out = NSMutableData(); let dest = CGImageDestinationCreateWithData(out, "public.jpeg" as CFString, 1, nil)!
        CGImageDestinationAddImage(dest, UIImage(data: png)!.cgImage!, [kCGImagePropertyGPSDictionary: [kCGImagePropertyGPSLatitude: 47.0, kCGImagePropertyGPSLongitude: 8.0]] as CFDictionary)
        CGImageDestinationFinalize(dest)
        let src0 = CGImageSourceCreateWithData(out, nil)!; XCTAssertNotNil((CGImageSourceCopyPropertiesAtIndex(src0, 0, nil) as? [CFString: Any])?[kCGImagePropertyGPSDictionary], "fixture has GPS")
        let jpg = try MediaPrep.jpeg(from: out as Data)
        let src = CGImageSourceCreateWithData(jpg as CFData, nil)!; let p = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as! [CFString: Any]
        XCTAssertEqual(CGImageSourceGetType(src) as String?, "public.jpeg")
        XCTAssertEqual(max(p[kCGImagePropertyPixelWidth] as! Int, p[kCGImagePropertyPixelHeight] as! Int), 2048)
        XCTAssertNil(p[kCGImagePropertyGPSDictionary])
        XCTAssertThrowsError(try MediaPrep.jpeg(from: Data("nope".utf8)))
        let small = try MediaPrep.jpeg(from: png.prefix(png.count) as Data, maxPixel: 100); XCTAssertNotNil(small)
    }
    func testLocationShare() {
        let l = CLLocation(coordinate: CLLocationCoordinate2D(latitude: 47.05, longitude: 8.3), altitude: 0, horizontalAccuracy: 12, verticalAccuracy: -1, timestamp: Date())
        XCTAssertEqual(LocationFetcher.share(from: l, label: "Luzern"), LocationShare(lat: 47.05, lon: 8.3, label: "Luzern", accuracyM: 12))
        let bad = CLLocation(coordinate: l.coordinate, altitude: 0, horizontalAccuracy: -1, verticalAccuracy: -1, timestamp: Date())
        XCTAssertNil(LocationFetcher.share(from: bad).accuracyM); XCTAssertNil(LocationFetcher.share(from: bad, label: "").label)
    }
    func testSpokenTextBounds() {
        XCTAssertEqual(SpokenText.make(text: "x ").count, 1)
        XCTAssertLessThanOrEqual(SpokenText.make(text: String(repeating: "word ", count: 400)).count, 900)
        XCTAssertEqual(SpokenText.make(text: "**   **"), "")
    }
}

@MainActor
final class SpeechPlayerTests: XCTestCase {
    @MainActor final class FakeAudio: AudioPlaying {
        var started: [Data] = [], rates: [Float] = [], onFinish: (@MainActor () -> Void)?, paused = false, stopped = 0
        func start(data: Data, rate: Float, onFinish: @escaping @MainActor () -> Void) throws { started.append(data); rates.append(rate); self.onFinish = onFinish }
        func pause() { paused = true }; func resume() { paused = false }; func stop() { stopped += 1 }
        func setRate(_ r: Float) { rates.append(r) }
        var currentTime: TimeInterval { 0 }; var duration: TimeInterval { 1 }
    }
    @MainActor final class FakeVoice: Synthesizing {
        var spoken: [String] = [], onFinish: (@MainActor () -> Void)?
        func speak(_ t: String, lang: String, rate: Float, onFinish: @escaping @MainActor () -> Void) { spoken.append(t); self.onFinish = onFinish }
        func stop() {}
    }
    final class Counter: @unchecked Sendable { var n = 0; var mode = 0 }

    private func make(_ c: Counter, audio: FakeAudio, voice: FakeVoice, dir: URL) -> SpeechPlayer {
        let d = UserDefaults(suiteName: "speech-" + UUID().uuidString)!
        return SpeechPlayer(fetch: { id, lang in
            c.n += 1
            switch c.mode { case 402: throw RelayError.api(status: 402, code: "tts_cap_reached", message: "cap"); case 404: throw RelayError.api(status: 404, code: "not_found", message: "x"); default: return Data("mp3-\(id)".utf8) }
        }, cacheDirectory: dir, audio: audio, synth: voice, defaults: d, systemControls: false)
    }
    private func clip(_ id: String) -> SpeechClip { SpeechClip(messageId: id, text: "Hello **there** https://x.ch", summary: nil, lang: "en", title: "P") }
    private func until(_ cond: () -> Bool) async { for _ in 0..<200 where !cond() { try? await Task.sleep(for: .milliseconds(10)) } }

    func testPlaysCachesRatesListenedAndAutoNext() async throws {
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let c = Counter(), a = FakeAudio(), v = FakeVoice(), p = make(c, audio: a, voice: v, dir: dir)
        p.play(clip("m_aaaaaaaaaaaaaaaa"), then: [clip("m_bbbbbbbbbbbbbbbb")])
        await until { a.started.count == 1 }
        XCTAssertEqual(p.state, .playing("m_aaaaaaaaaaaaaaaa")); XCTAssertEqual(a.started[0], Data("mp3-m_aaaaaaaaaaaaaaaa".utf8))
        p.cycleRate(); XCTAssertEqual(p.rate, 1.5); p.cycleRate(); XCTAssertEqual(p.rate, 2); p.cycleRate(); XCTAssertEqual(p.rate, 1)
        a.onFinish?()
        await until { a.started.count == 2 }
        XCTAssertTrue(p.isListened("m_aaaaaaaaaaaaaaaa")); XCTAssertFalse(p.isListened("m_bbbbbbbbbbbbbbbb")); XCTAssertEqual(p.state, .playing("m_bbbbbbbbbbbbbbbb"))
        a.onFinish?(); await until { p.state == .idle }
        XCTAssertTrue(p.isListened("m_bbbbbbbbbbbbbbbb"))
        p.play(clip("m_aaaaaaaaaaaaaaaa")); await until { a.started.count == 3 }
        XCTAssertEqual(c.n, 2, "m_a came from the disk cache the second time")
    }
    func testCapReachedFallsBackToPhoneVoiceAndOtherErrorsStop() async throws {
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let c = Counter(), a = FakeAudio(), v = FakeVoice(), p = make(c, audio: a, voice: v, dir: dir)
        c.mode = 402; p.play(clip("m_aaaaaaaaaaaaaaaa")); await until { !v.spoken.isEmpty }
        XCTAssertEqual(v.spoken, ["Hello there link"]); XCTAssertTrue(p.usingPhoneVoice); XCTAssertNotNil(p.notice)
        v.onFinish?(); await until { p.state == .idle }; XCTAssertTrue(p.isListened("m_aaaaaaaaaaaaaaaa"))
        c.mode = 404; p.play(clip("m_bbbbbbbbbbbbbbbb")); await until { p.state == .idle && p.current == nil }
        XCTAssertTrue(v.spoken.count == 1); XCTAssertFalse(p.isListened("m_bbbbbbbbbbbbbbbb"))
    }
    func testBadMessageIdNeverTouchesTheCachePath() async throws {
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let c = Counter(), a = FakeAudio(), v = FakeVoice(), p = make(c, audio: a, voice: v, dir: dir)
        p.play(SpeechClip(messageId: "../../etc/evil", text: "x", summary: nil, lang: "en", title: "P"))
        await until { p.state == .idle && p.current == nil }
        XCTAssertEqual(c.n, 0, "not even fetched"); XCTAssertTrue(a.started.isEmpty); XCTAssertTrue(v.spoken.isEmpty)
        XCTAssertTrue(SpeechPlayer.isValidMessageId("m_abcdefghij012345")); XCTAssertFalse(SpeechPlayer.isValidMessageId("m_a/b"))
    }
    func testCacheEvictsLeastRecentlyUsedOverTheCap() throws {
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let old = file(dir, "old.mp3", bytes: 600), mid = file(dir, "mid.mp3", bytes: 600), new = file(dir, "new.mp3", bytes: 600)
        let fm = FileManager.default
        try fm.setAttributes([.modificationDate: Date(timeIntervalSinceNow: -300)], ofItemAtPath: old.path)
        try fm.setAttributes([.modificationDate: Date(timeIntervalSinceNow: -200)], ofItemAtPath: mid.path)
        SpeechPlayer.evict(dir, limit: 1300, keep: new)
        XCTAssertFalse(fm.fileExists(atPath: old.path)); XCTAssertTrue(fm.fileExists(atPath: mid.path)); XCTAssertTrue(fm.fileExists(atPath: new.path))
        XCTAssertEqual(SpeechPlayer.cacheLimitBytes, 50 * 1024 * 1024)
    }
    func testPausingThePhoneVoiceKeepsTheQueue() async throws {
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let c = Counter(), a = FakeAudio(), v = FakeVoice(), p = make(c, audio: a, voice: v, dir: dir)
        c.mode = 402; p.play(clip("m_aaaaaaaaaaaaaaaa"), then: [clip("m_bbbbbbbbbbbbbbbb")]); await until { !v.spoken.isEmpty }
        p.pause()
        XCTAssertEqual(p.state, .idle); XCTAssertNil(p.current); XCTAssertEqual(p.queue.map(\.messageId), ["m_bbbbbbbbbbbbbbbb"]); XCTAssertFalse(p.usingPhoneVoice)
    }
    func testPauseResume() async throws {
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let c = Counter(), a = FakeAudio(), v = FakeVoice(), p = make(c, audio: a, voice: v, dir: dir)
        p.play(clip("m_aaaaaaaaaaaaaaaa")); await until { a.started.count == 1 }
        p.pause(); XCTAssertEqual(p.state, .paused("m_aaaaaaaaaaaaaaaa")); XCTAssertTrue(a.paused); p.resume(); XCTAssertEqual(p.state, .playing("m_aaaaaaaaaaaaaaaa")); p.stop(); XCTAssertEqual(p.state, .idle)
    }
}

@MainActor
final class VoiceV3Tests: XCTestCase {
    func testRecorderSplitsAtTheCap() async throws {
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let r = VoiceRecorder(mode: .scripted, maxSegmentSeconds: 0.25, directory: dir)
        try await r.start()
        try await Task.sleep(for: .milliseconds(700))
        XCTAssertTrue(r.isRecording); XCTAssertEqual(r.levels.count, VoiceRecorder.barCount); XCTAssertTrue(r.levels.contains { $0 > 0 })
        let segs = r.stop()
        XCTAssertGreaterThanOrEqual(segs.count, 2, "auto-split"); XCTAssertFalse(r.isRecording)
        for s in segs { XCTAssertTrue(FileManager.default.fileExists(atPath: s.url.path)) }
        r.cancel(); XCTAssertTrue(r.finished.isEmpty)
    }
    func testTranscriberUsesSwissGermanSettingThenOnDevice() async throws {
        let dir = tmpDir(); defer { try? FileManager.default.removeItem(at: dir) }
        let f = file(dir, "v.m4a"); final class Seen: @unchecked Sendable { var lang: String?? = nil }; let seen = Seen()
        let ok = VoiceTranscriber(relay: { _, l in seen.lang = .some(l); return Transcript(text: "hallo", language: "de", duration: 1) }, onDevice: { _, _ in "x" }, deviceLanguage: "en")
        var t = await ok.transcribe(file: f, swissGerman: true)
        XCTAssertEqual(seen.lang, .some("de-CH")); XCTAssertEqual(t.lang, "de-CH"); XCTAssertEqual(t.langSource, .setting); XCTAssertFalse(t.usedOnDevice)
        t = await ok.transcribe(file: f, swissGerman: false); XCTAssertEqual(t.langSource, .detected); XCTAssertEqual(t.lang, "de")
        t = await ok.transcribe(file: f, swissGerman: true, corrected: "en"); XCTAssertEqual(t.langSource, .corrected); XCTAssertEqual(t.lang, "en")
        let off = VoiceTranscriber(relay: { _, _ in throw RelayError.api(status: 503, code: "transcription_off", message: "") }, onDevice: { _, l in "local \(l)" }, deviceLanguage: "en")
        t = await off.transcribe(file: f, swissGerman: false); XCTAssertEqual(t.text, "local en"); XCTAssertTrue(t.usedOnDevice)
        let broken = VoiceTranscriber(relay: { _, _ in throw RelayError.network("x") }, onDevice: { _, _ in throw RelayError.network("y") }, deviceLanguage: "en")
        t = await broken.transcribe(file: f, swissGerman: false); XCTAssertTrue(t.failed); XCTAssertEqual(t.text, "")
        let tooBig = VoiceTranscriber(relay: { _, _ in throw RelayError.api(status: 413, code: "too_large", message: "") }, onDevice: { _, _ in "never" }, deviceLanguage: "en")
        t = await tooBig.transcribe(file: f, swissGerman: false); XCTAssertTrue(t.failed, "no on-device fallback for a refusal")
    }
}

// MARK: AppModel API for the screens

@MainActor
final class AppModelV3Tests: XCTestCase {
    var dir: URL!
    override func setUp() async throws { Keychain.delete(); dir = tmpDir(); UserDefaults.standard.removeObject(forKey: "mockFail"); UserDefaults.standard.removeObject(forKey: "chatRead") }
    override func tearDown() async throws { Keychain.delete(); try? FileManager.default.removeItem(at: dir); UserDefaults.standard.removeObject(forKey: "chatRead") }
    private func paired() async -> AppModel {
        let m = AppModel(useMock: true, voiceMode: .scripted, outboxDirectory: dir, speechCache: dir.appendingPathComponent("sp"), systemAudioControls: false)
        m.openSampleInvite(); await m.connect(phoneName: "T"); await m.finishSetup(allowNotifications: false); return m
    }

    func testNewTopicBecomesATopicAfterTheAck() async throws {
        let m = await paired()
        let item = try await m.send(MessageDraft(text: "Please check the invoices"), to: .newTopic(workspace: MockRelay.reports))
        XCTAssertNotNil(item.sentMessageId)
        await m.refresh()
        XCTAssertTrue(m.outbox.items.isEmpty)
        let ws = m.workspaceSummaries.first { $0.id == MockRelay.reports }!
        XCTAssertTrue(ws.topics.contains { $0.title.contains("Please check") && !$0.isStarting }, "the ack moved it into its own topic")
        let id = m.resolve(.starting(workspace: MockRelay.reports, id: item.clientId))
        XCTAssertNotNil(id.ticket)
        XCTAssertEqual(m.conversationItems(id).first?.receipt, .started)
    }
    func testGeneralMessageTicksAndUnread() async throws {
        let m = await paired()
        _ = try await m.send(MessageDraft(text: "hi"), to: .general(workspace: MockRelay.pilatus)); await m.refresh()
        let items = m.conversationItems(.general(workspace: MockRelay.pilatus))
        XCTAssertEqual(items.last?.text, "hi"); XCTAssertEqual(items.last?.receipt, .started)
        // Pilatus has an old workspace text in General: unread until opened
        XCTAssertEqual(m.unread(.general(workspace: MockRelay.pilatus)), 1)
        m.markRead(.general(workspace: MockRelay.pilatus)); XCTAssertEqual(m.unread(.general(workspace: MockRelay.pilatus)), 0)
    }
    func testOfflineMessageWaitsThenGoesOnRefreshWithOneClientId() async throws {
        let m = await paired()
        await m.mock!.setOffline(true)
        let item = try await m.send(MessageDraft(text: "later"), to: .general(workspace: MockRelay.pilatus))
        XCTAssertNil(item.sentMessageId); XCTAssertEqual(m.conversationItems(.general(workspace: MockRelay.pilatus)).last?.receipt, .queued)
        await m.mock!.setOffline(false)
        await m.refresh()
        XCTAssertTrue(m.outbox.items.isEmpty)
        XCTAssertEqual(m.messages.filter { $0.message.body.text == "later" && $0.clientId == item.clientId }.count, 1)
    }
    func testSettingsMuteRemoveAndInvitation() async throws {
        let m = await paired()
        XCTAssertEqual(m.settings, PhoneSettings())
        await m.updateSettings(SettingsPatch(speak: .always, swissGerman: true)); XCTAssertEqual(m.settings.speak, .always); XCTAssertTrue(m.settings.swissGerman)
        await m.updateSettings(SettingsPatch(ttsCapUsd: 500)); XCTAssertEqual(m.settings.ttsCapUsd, 10, "invalid patch is not sent")
        await m.setMute(MockRelay.pilatus, .forever); XCTAssertTrue(m.workspace(MockRelay.pilatus)!.isMuted())
        await m.setMute(MockRelay.pilatus, .off); XCTAssertFalse(m.workspace(MockRelay.pilatus)!.isMuted())
        let added = await m.redeemInvitation(PairingLink.sample.link); XCTAssertEqual(added.map(\.id), ["ws_home000001"]); XCTAssertEqual(m.workspaces.count, 3)
        let again = await m.redeemInvitation(PairingLink.sample.link); XCTAssertTrue(again.isEmpty); XCTAssertNotNil(m.message)
        await m.removeWorkspace(MockRelay.reports)
        XCTAssertNil(m.workspace(MockRelay.reports)); XCTAssertTrue(m.messages.allSatisfy { $0.workspaceId != MockRelay.reports })
    }
    func testUnauthorizedOnMessagesSignsOut() async throws {
        let m = await paired()
        try await m.mock!.signOut()
        await m.reloadMessages()
        XCTAssertEqual(m.phase, .onboarding)
    }
    func testSentMessageBeyondPageOneIsStillReconciled() async throws {
        let m = await paired(); m.pageSize = 2
        let relay = m.mock!
        let item = try m.outbox.enqueue(MessageDraft(text: "buried"), to: .general(workspace: MockRelay.pilatus))
        await m.outbox.flush(using: relay)
        XCTAssertNotNil(m.outbox.item(clientId: item.clientId)?.sentMessageId)
        for i in 0..<4 { await relay.deliverText(from: MockRelay.pilatus, text: "later \(i)"); try await Task.sleep(for: .milliseconds(1100)) }
        await m.reloadMessages()
        XCTAssertNil(m.outbox.item(clientId: item.clientId), "found by paging on, so it left the outbox")
    }
    func testPaginationLoadsOlderPages() async throws {
        let relay = MockRelay(latency: .zero)
        let all = try await relay.messages(after: nil, limit: nil).items
        let p1 = try await relay.messages(after: nil, limit: 2)
        XCTAssertEqual(p1.items.count, 2); XCTAssertNotNil(p1.next)
        let p2 = try await relay.messages(after: p1.next, limit: 100)
        XCTAssertEqual(p1.items.count + p2.items.count, all.count); XCTAssertNil(p2.next)
        do { _ = try await relay.messages(after: "m_nope", limit: 1); XCTFail() } catch let RelayError.api(st, _, _) { XCTAssertEqual(st, 422) }
    }
    func testSignOutWipesOutboxAndSpeech() async throws {
        let m = await paired()
        await m.mock!.setOffline(true)
        _ = try await m.send(MessageDraft(text: "x"), to: .general(workspace: MockRelay.pilatus))
        XCTAssertEqual(m.outbox.items.count, 1)
        await m.mock!.setOffline(false)
        await m.signOut()
        XCTAssertTrue(m.outbox.items.isEmpty); XCTAssertTrue(Outbox(directory: dir, phone: "ph_iphone0001").items.isEmpty)
    }
    func testPushPayloadTicket() {
        XCTAssertEqual(PushPayload.ticket(["ticket": "t_q3sum1"]), "t_q3sum1"); XCTAssertNil(PushPayload.ticket(["ticket": "../x"])); XCTAssertNil(PushPayload.ticket([:]))
    }
}
