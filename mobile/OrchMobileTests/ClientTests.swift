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
        XCTAssertNil(r.items[0].description); XCTAssertEqual(lastSeenText(nil, online: false), "Offline")
    }
}
