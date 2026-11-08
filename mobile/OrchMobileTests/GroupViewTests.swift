import XCTest
@testable import OrchMobile

final class GroupViewTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private func snapshot(_ messages: [PhoneMessage]) -> GroupSnapshot {
        GroupStore.build(messages: messages.sorted { $0.message.createdAt > $1.message.createdAt }, workspaces: GroupMock.names,
                         ownPhoneId: "ph_iphone0001", ownMessageIds: [])
    }
    func testThinkingShowsAndExpires() throws {
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        XCTAssertEqual(GroupRoomRules.thinking(group: group, now: now), [GroupMock.home])
        XCTAssertEqual(GroupRoomRules.thinking(group: group, now: now.addingTimeInterval(600)), [])
    }
    func testThinkingEndsOnLaterMemberText() throws {
        var messages = GroupMock.messages(now: now)
        let source = try XCTUnwrap(messages.first { $0.message.body.task != nil })
        var body = source.message.body
        body.update = nil; body.task = nil; body.text = "I found the letter."
        body.group?.seq = 9
        body.origin = GroupOrigin(id: "origin_result", from: GroupMock.home, at: ISO8601DateFormatter().string(from: now))
        messages.append(PhoneMessage(message: TextMessage(id: "m_groupresult001", from: GroupMock.finance, to: "phones", type: "text",
            createdAt: ISO8601DateFormatter().string(from: now), ticket: GroupMock.ticket, body: body, key: "FIN-14"), workspaceName: "Finance"))
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(messages)).first)
        XCTAssertEqual(GroupRoomRules.thinking(group: group, now: now), [])
    }
    func testListSeparatesOpenAndHistoryAndFixturePassesRules() {
        let data = snapshot(GroupMock.messages(now: now))
        XCTAssertEqual(data.dropped, [])
        XCTAssertEqual(GroupRoomRules.rows(data).map(\.title), ["Pay car tax 2027"])
        XCTAssertEqual(GroupRoomRules.rows(data, closed: true).map(\.title), ["Pay car tax 2026"])
    }
    func testTaskLabels() {
        let labels = ["waiting_start": "Waiting for Home to start", "waiting_approval": "Waiting for approval", "queued": "Queued",
                      "working": "Working", "done": "Done", "failed": "Failed", "denied": "No"]
        for (status, label) in labels { XCTAssertEqual(GroupRoomRules.taskLabel(status, name: "Home"), label) }
    }
    func testApprovalUsesBankQuestion() throws {
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        let event = try XCTUnwrap(group.messages.compactMap(\.event).first { $0.kind == "approval_needed" })
        let question = GroupMock.question(at: ISO8601DateFormatter().string(from: now))
        XCTAssertEqual(GroupStore.approvalCard(for: event, in: group, questions: [question]), .buttons(question))
    }

    @MainActor func testGroupSendUsesNewestHostCopy() async throws {
        let defaults = UserDefaults.standard
        let previous = defaults.object(forKey: "mockGroups")
        defaults.set(true, forKey: "mockGroups")
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer {
            defaults.set(previous, forKey: "mockGroups")
            Keychain.delete()
            try? FileManager.default.removeItem(at: dir)
        }
        Keychain.delete()
        let model = AppModel(useMock: true, voiceMode: .scripted, outboxDirectory: dir, speechCache: dir.appendingPathComponent("speech"), systemAudioControls: false)
        model.openSampleInvite()
        await model.connect(phoneName: "Test")
        await model.finishSetup(allowNotifications: false)
        let group = try XCTUnwrap(GroupRoomRules.rows(model.groups).first)
        try await model.sendGroup(MessageDraft(text: "Please check the payment.", replyTo: "stale"), key: group.key)
        let mock = try XCTUnwrap(model.mock)
        let requests = await mock.requests
        let request = try XCTUnwrap(requests.last)
        XCTAssertEqual(request.to, GroupMock.finance)
        XCTAssertEqual(request.ticket, GroupMock.ticket)
        XCTAssertEqual(request.replyTo, GroupStore.replyTarget(in: group))
        XCTAssertEqual(request.replyTo, "m_groupcopy00008")
    }
}
