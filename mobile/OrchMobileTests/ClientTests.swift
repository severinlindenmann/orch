import XCTest
@testable import OrchMobile

final class ClientTests: XCTestCase {
    let base = URL(string: "https://relay.severin.io")!
    let creds = Credentials(relay: URL(string: "https://relay.severin.io")!, phoneId: "ph_iphone0001",
                            token: "orn_ph9Lq2Wm4Er7Ty1Ui3Op5As8Df0Gh6Jk2Lz4Xc7Vb9", phoneName: "Severin's iPhone")

    func client(_ ex: Example) -> URLSessionRelayClient {
        StubProtocol.handler = { _ in (ex.status, ex.responseData) }
        return URLSessionRelayClient(base: base, credentials: creds, session: StubProtocol.session())
    }

    func testPairDecodesAndSendsNoAuth() async throws {
        let ex = try Example.find("POST", "/v1/phone/pair")
        let r = try await client(ex).pair(code: "pc_Tg5Yh7Uj9Ik2Ol4Pz6Xc8V", name: "Severin's iPhone")
        XCTAssertEqual(r.phoneId, "ph_iphone0001")
        XCTAssertTrue(r.token.hasPrefix("orn_"))
        XCTAssertEqual(r.workspaces.map(\.name), ["Pilatus Workspace", "Home"])
        let req = StubProtocol.seen[0]
        XCTAssertEqual(req.httpMethod, "POST"); XCTAssertEqual(req.url?.path, "/v1/phone/pair")
        XCTAssertNil(req.value(forHTTPHeaderField: "Authorization"))
        let body = try JSONSerialization.jsonObject(with: StubProtocol.seenBodies[0]) as! [String: String]
        XCTAssertEqual(body, ["code": "pc_Tg5Yh7Uj9Ik2Ol4Pz6Xc8V", "name": "Severin's iPhone"])
    }

    func testWorkspacesDecodeWithPhoneAuth() async throws {
        let ws = try await client(Example.find("GET", "/v1/phone/workspaces")).workspaces()
        XCTAssertEqual(ws.count, 2)
        XCTAssertEqual(ws[0].openQuestions, 1); XCTAssertEqual(ws[0].tags, ["data", "work"]); XCTAssertTrue(ws[0].online)
        XCTAssertEqual(ws[1].description, "Private tasks: household, travel, home automation.")
        let req = StubProtocol.seen[0]
        XCTAssertEqual(req.value(forHTTPHeaderField: "X-Orch-Phone"), "ph_iphone0001")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer \(creds.token)")
    }

    func testQuestionsDecode() async throws {
        let qs = try await client(Example.find("GET", "/v1/phone/questions")).questions()
        XCTAssertEqual(qs.count, 1)
        XCTAssertEqual(qs[0].id, "m_q1date0ts0000001"); XCTAssertEqual(qs[0].workspaceName, "Pilatus Workspace")
        XCTAssertEqual(qs[0].message.body.text, "DATE or TIMESTAMP?"); XCTAssertEqual(qs[0].message.body.options, ["DATE", "TIMESTAMP"])
        XCTAssertEqual(qs[0].message.body.recommended, "TIMESTAMP"); XCTAssertEqual(qs[0].message.ticket, "t_7k3f9q")
    }

    func testAnswerRequestShapeAndId() async throws {
        let id = try await client(Example.find("POST", "/v1/phone/answer", status: 201)).answer(questionMessageId: "m_q1date0ts0000001", answer: "TIMESTAMP")
        XCTAssertEqual(id, "m_an5wer7q2w9e4r6t")
        let body = try JSONSerialization.jsonObject(with: StubProtocol.seenBodies[0]) as! [String: String]
        XCTAssertEqual(body, ["question_message_id": "m_q1date0ts0000001", "answer": "TIMESTAMP"])
    }

    func testSecondAnswerIs409AlreadyAnswered() async throws {
        let c = try client(Example.find("POST", "/v1/phone/answer", status: 409))
        do { _ = try await c.answer(questionMessageId: "m_q1date0ts0000001", answer: "DATE"); XCTFail("expected error") }
        catch let RelayError.api(status, code, message) {
            XCTAssertEqual(status, 409); XCTAssertEqual(code, "already_answered"); XCTAssertEqual(message, "This question was already answered: TIMESTAMP.")
        }
    }

    func testSendBodyHasNullTicket() async throws {
        let id = try await client(Example.find("POST", "/v1/phone/send")).send(to: "ws_home000001", text: "Book the train to Lucerne for Friday", ticket: nil)
        XCTAssertEqual(id, "m_ph0nesend7q2w9e4")
        let body = try JSONSerialization.jsonObject(with: StubProtocol.seenBodies[0]) as! [String: Any]
        XCTAssertEqual(body["to"] as? String, "ws_home000001"); XCTAssertEqual(body["text"] as? String, "Book the train to Lucerne for Friday")
    }

    func testPushRegistrationBody() async throws {
        try await client(Example.find("POST", "/v1/phone/push")).registerPush(apnsToken: "abc123", sandbox: true)
        let body = try JSONSerialization.jsonObject(with: StubProtocol.seenBodies[0]) as! [String: Any]
        XCTAssertEqual(body["apns_token"] as? String, "abc123"); XCTAssertEqual(body["sandbox"] as? Bool, true)
    }

    func testSignOutAndUnauthorized() async throws {
        try await client(Example.find("POST", "/v1/phone/signout")).signOut()
        XCTAssertEqual(StubProtocol.seen[0].url?.path, "/v1/phone/signout")
        StubProtocol.handler = { _ in (401, Data(#"{"error":"unauthorized","message":"no"}"#.utf8)) }
        let c = URLSessionRelayClient(base: base, credentials: creds, session: StubProtocol.session())
        StubProtocol.handler = { _ in (401, Data(#"{"error":"unauthorized","message":"no"}"#.utf8)) }
        do { _ = try await c.workspaces(); XCTFail() } catch { XCTAssertEqual(error as? RelayError, .unauthorized) }
    }

    func testIgnoresUnknownFields() throws {
        let json = #"{"items":[{"id":"ws_a","name":"A","description":null,"tags":[],"online":false,"last_seen":null,"open_questions":0,"new_field":1}],"next":null}"#
        let r = try JSONCoding.decoder.decode(ListResponse<Workspace>.self, from: Data(json.utf8))
        XCTAssertNil(r.items[0].description); XCTAssertEqual(lastSeenText(nil, online: false), "Asleep. Questions arrive when it wakes up.")
    }

    func testDisplayNamesAndDedupe() {
        XCTAssertEqual(displayName(" Pilatus Workspace "), "Pilatus Workspace")
        XCTAssertEqual(displayName("Pilatus Workspace"), "Pilatus Workspace"); XCTAssertEqual(displayName("Reports"), "Reports")
        func q(_ id: String, _ at: String) -> Question {
            Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: "ws_a", to: "phones", type: "question", createdAt: at, ticket: "t_1",
                body: QuestionBody(questionId: "q1", title: "T", text: "Ship it?", options: ["Yes", "No"], recommended: nil)), workspaceName: "a")
        }
        let list = [q("m_1", "2026-11-04T10:00:00Z"), q("m_2", "2026-11-04T10:01:00Z"), q("m_2", "2026-11-04T10:01:00Z"), q("m_3", "2026-11-04T10:02:00Z")]
        XCTAssertEqual(list.deduplicated().map(\.id), ["m_3"])
    }

    func testTranscribeSendsAudioAndDecodes() async throws {
        StubProtocol.handler = { _ in (200, Data(#"{"text":"Nimm das Feld event_time.","language":"de","duration":2.4}"#.utf8)) }
        let c = URLSessionRelayClient(base: base, credentials: creds, session: StubProtocol.session())
        let t = try await c.transcribe(audio: Data([1, 2, 3]), language: "de")
        XCTAssertEqual(t, Transcript(text: "Nimm das Feld event_time.", language: "de", duration: 2.4))
        let req = StubProtocol.seen[0]
        XCTAssertEqual(req.httpMethod, "POST"); XCTAssertEqual(req.url?.path, "/v1/phone/transcribe")
        XCTAssertEqual(req.url?.query, "language=de")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Content-Type"), "audio/m4a")
        XCTAssertEqual(req.value(forHTTPHeaderField: "X-Orch-Phone"), "ph_iphone0001")
        XCTAssertEqual(StubProtocol.seenBodies[0], Data([1, 2, 3]))
    }

    func testTranscribeOffIs503() async throws {
        StubProtocol.handler = { _ in (503, Data(#"{"error":"transcription_off","message":"Voice transcription is not set up on this relay."}"#.utf8)) }
        let c = URLSessionRelayClient(base: base, credentials: creds, session: StubProtocol.session())
        do { _ = try await c.transcribe(audio: Data([1]), language: nil); XCTFail() }
        catch { XCTAssertTrue(VoiceInput.shouldUseOnDevice(error)) }
    }
}

@MainActor
final class VoiceFallbackTests: XCTestCase {
    private func tmpAudio() throws -> URL {
        let u = FileManager.default.temporaryDirectory.appendingPathComponent("t-\(UUID().uuidString).m4a")
        try Data([9, 9]).write(to: u); return u
    }

    func testFallbackRules() {
        XCTAssertTrue(VoiceInput.shouldUseOnDevice(RelayError.api(status: 503, code: "transcription_off", message: "")))
        XCTAssertTrue(VoiceInput.shouldUseOnDevice(RelayError.network("x")))
        XCTAssertFalse(VoiceInput.shouldUseOnDevice(RelayError.api(status: 429, code: "rate_limited", message: "")))
        XCTAssertFalse(VoiceInput.shouldUseOnDevice(RelayError.api(status: 502, code: "transcription_failed", message: "")))
        XCTAssertEqual(VoiceInput.message(for: RelayError.api(status: 502, code: "transcription_failed", message: "")), "Couldn't transcribe, try again.")
    }

    func testTranscriptionOffUsesOnDevice() async throws {
        let file = try tmpAudio(); defer { try? FileManager.default.removeItem(at: file) }
        let v = VoiceInput(mode: .file(file),
                           transcribe: { _ in throw RelayError.api(status: 503, code: "transcription_off", message: "off") },
                           onDevice: { _ in "from this phone" })
        await v.toggle(current: "Hello"); await v.toggle(current: "")
        XCTAssertEqual(v.transcript, "Hello from this phone"); XCTAssertTrue(v.usedOnDevice); XCTAssertNil(v.error)
    }

    func testRelayTextWinsAndOnDeviceNotCalled() async throws {
        let file = try tmpAudio(); defer { try? FileManager.default.removeItem(at: file) }
        let v = VoiceInput(mode: .file(file), transcribe: { _ in "from the relay" },
                           onDevice: { _ in XCTFail("on-device must not run"); return "" })
        await v.toggle(current: ""); await v.toggle(current: "")
        XCTAssertEqual(v.transcript, "from the relay"); XCTAssertFalse(v.usedOnDevice)
    }

    func testRateLimitShowsPlainMessageNoFallback() async throws {
        let file = try tmpAudio(); defer { try? FileManager.default.removeItem(at: file) }
        let v = VoiceInput(mode: .file(file),
                           transcribe: { _ in throw RelayError.api(status: 429, code: "rate_limited", message: "slow") },
                           onDevice: { _ in XCTFail("no fallback on 429"); return "" })
        await v.toggle(current: ""); await v.toggle(current: "")
        XCTAssertEqual(v.error, "Too many recordings in a row. Wait a moment and try again."); XCTAssertEqual(v.transcript, "")
    }

    func testBothFailShowsTryAgain() async throws {
        let file = try tmpAudio(); defer { try? FileManager.default.removeItem(at: file) }
        let v = VoiceInput(mode: .file(file), transcribe: { _ in throw RelayError.network("down") },
                           onDevice: { _ in throw RelayError.network("no speech") })
        await v.toggle(current: ""); await v.toggle(current: "")
        XCTAssertEqual(v.error, "Couldn't transcribe, try again.")
    }
}
