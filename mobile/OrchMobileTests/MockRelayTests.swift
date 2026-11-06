import XCTest
@testable import OrchMobile

final class MockRelayTests: XCTestCase {
    func testDatasetAndFirstAnswerWins() async throws {
        let m = MockRelay(latency: .zero)
        let ws = try await m.workspaces()
        XCTAssertEqual(ws.map(\.name), ["Pilatus Workspace", "Reports"]); XCTAssertEqual(ws.map(\.openQuestions), [1, 1])
        let qs = try await m.questions()
        XCTAssertEqual(qs.map(\.message.body.text), ["DATE or TIMESTAMP?", "Send the report on Friday this week?"])
        _ = try await m.answer(questionMessageId: qs[0].id, answer: "TIMESTAMP")
        do { _ = try await m.answer(questionMessageId: qs[0].id, answer: "DATE"); XCTFail() }
        catch let RelayError.api(status, code, _) { XCTAssertEqual(status, 409); XCTAssertEqual(code, "already_answered") }
        let left = try await m.questions(); XCTAssertEqual(left.count, 1)
    }
    func testMessagesShowReplyAndWhatThePhoneSent() async throws {
        let relay = MockRelay(latency: .milliseconds(1))
        func plain() async throws -> [PhoneMessage] { try await relay.messages().filter { $0.message.body.update == nil } }
        var ms = try await plain()
        XCTAssertEqual(ms.map(\.message.from).sorted(), ["ph_iphone0001", MockRelay.pilatus])
        _ = try await relay.send(to: MockRelay.pilatus, text: "hello", ticket: nil)
        await relay.deliverText(from: MockRelay.reports, text: "done")
        ms = try await plain()
        XCTAssertEqual(ms.count, 4)
        XCTAssertEqual(Set(ms.map(\.workspaceId)), [MockRelay.pilatus, MockRelay.reports])
        XCTAssertTrue(ms.contains { $0.fromPhone && $0.message.body.text == "hello" })
    }

    func testSendOnlyToReachable() async throws {
        let m = MockRelay(latency: .zero)
        _ = try await m.send(to: MockRelay.reports, text: "hi", ticket: nil)
        do { _ = try await m.send(to: "ws_other00001", text: "x", ticket: nil); XCTFail() } catch { XCTAssertEqual((error as? RelayError).map { if case .api(let s, _, _) = $0 { s } else { 0 } }, 403) }
    }
    func testSignOutGives401() async throws {
        let m = MockRelay(latency: .zero); try await m.signOut()
        do { _ = try await m.workspaces(); XCTFail() } catch { XCTAssertEqual(error as? RelayError, .unauthorized) }
    }
}

@MainActor
final class AppModelTests: XCTestCase {
    override func setUp() async throws { Keychain.delete() }
    override func tearDown() async throws { Keychain.delete() }

    func testPairAnswerSendSignOutFlow() async throws {
        let model = AppModel(useMock: true, voiceMode: .scripted)
        XCTAssertEqual(model.phase, .onboarding)
        model.openInvite("garbage"); XCTAssertNotNil(model.message)
        model.openSampleInvite()
        XCTAssertEqual(model.inviteState, .found(host: "relay.severin.io"))
        await model.connect(phoneName: "Test phone")
        XCTAssertEqual(model.phase, .notifyStep); XCTAssertEqual(model.pairedWorkspaces.count, 2)
        XCTAssertNotNil(Keychain.load())
        await model.finishSetup(allowNotifications: false)
        XCTAssertEqual(model.phase, .ready); XCTAssertEqual(model.openQuestionCount, 2); XCTAssertEqual(model.workspaces.count, 2)
        await model.answer(model.questions[0], with: "TIMESTAMP")
        XCTAssertEqual(model.openQuestionCount, 1)
        let ok = await model.sendChat(to: MockRelay.reports, text: "  Check totals  ")
        guard case .sent = ok else { return XCTFail("not sent") }
        let empty = await model.sendChat(to: MockRelay.reports, text: "   "); XCTAssertEqual(empty, .failed)
        await model.signOut()
        XCTAssertEqual(model.phase, .onboarding); XCTAssertNil(Keychain.load()); XCTAssertTrue(model.workspaces.isEmpty)
    }

    func testExpiredInvitationGivesFriendlyMessage() async throws {
        let model = AppModel(useMock: true, voiceMode: .scripted)
        model.openInvite("orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_expired0000000000000000")
        await model.connect(phoneName: "Test phone")
        XCTAssertEqual(model.message, "This invitation has expired or was already used. Ask the person who invited you for a new one.")
        XCTAssertEqual(model.inviteState, .found(host: "relay.severin.io"))
        XCTAssertEqual(model.phase, .onboarding)
    }

    func testLastUpdatedSaysJustNow() async throws {
        let model = AppModel(useMock: true, voiceMode: .scripted)
        model.openSampleInvite(); await model.connect(phoneName: "T"); await model.finishSetup(allowNotifications: false)
        XCTAssertEqual(model.lastUpdatedText, "Last updated just now")
    }

    func testPushTapOpensQuestion() async throws {
        let model = AppModel(useMock: true, voiceMode: .scripted)
        model.openQuestion(messageId: "m_q1date0ts0000001")
        XCTAssertEqual(model.tab, .chats); XCTAssertEqual(model.focusedQuestion, "m_q1date0ts0000001")
    }

    func testScriptedRecorderTranscribesViaMock() async throws {
        let model = AppModel(useMock: true, voiceMode: .scripted)
        let v = VoiceInput(mode: .scripted, transcribe: { try await model.transcribe($0) })
        await v.toggle(current: "")
        XCTAssertTrue(v.isRecording)
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertTrue(v.levels.contains { $0 > 0 })
        await v.toggle(current: "")
        XCTAssertFalse(v.isRecording); XCTAssertFalse(v.isTranscribing)
        XCTAssertEqual(v.transcript, MockRelay.transcript); XCTAssertNil(v.error)
    }
}
