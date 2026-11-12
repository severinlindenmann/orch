import XCTest
import UserNotifications
@testable import OrchMobile

@MainActor
final class PushTests: XCTestCase {
    func testPayloadParsingNeverTraps() {
        XCTAssertEqual(PushPayload.messageId(["aps": ["alert": "x"], "message_id": "m_q1date0ts0000001", "workspace": "ws_1"]), "m_q1date0ts0000001")
        XCTAssertNil(PushPayload.messageId([:]))
        XCTAssertNil(PushPayload.messageId(["message_id": 42]))
        XCTAssertNil(PushPayload.messageId(["message_id": ""]))
        XCTAssertNil(PushPayload.messageId(["message_id": NSNull()]))
    }

    func testTapOpensQuestionOnTheModel() {
        let model = AppModel(useMock: true)
        AppDelegate.model = model
        AppDelegate.handleTap(messageId: "m_q2friday00000002")
        XCTAssertEqual(model.focusedQuestion, "m_q2friday00000002")
        XCTAssertEqual(model.tab, .chats)
        AppDelegate.model = nil
    }

    func testTapBeforeModelExistsIsKeptForLater() {
        AppDelegate.model = nil
        AppDelegate.handleTap(messageId: "m_q1date0ts0000001")
        XCTAssertEqual(AppDelegate.pendingQuestion, "m_q1date0ts0000001")
        let model = AppModel(useMock: true)
        AppDelegate.model = model
        XCTAssertNil(AppDelegate.pendingQuestion)
        XCTAssertEqual(model.focusedQuestion, "m_q1date0ts0000001")
        AppDelegate.model = nil
    }

    func testTapWithoutIdIsIgnored() {
        let model = AppModel(useMock: true)
        AppDelegate.model = model
        AppDelegate.handleTap(messageId: nil)
        XCTAssertNil(model.focusedQuestion)
        AppDelegate.model = nil
    }
}

@MainActor
final class TextPushTests: XCTestCase {
    func testTextPayloadParsing() {
        XCTAssertEqual(PushPayload.textWorkspace(["type": "text", "text_id": "m_x", "workspace": "ws_1"]), "ws_1")
        XCTAssertNil(PushPayload.textWorkspace(["message_id": "m_q", "workspace": "ws_1"]))
        XCTAssertNil(PushPayload.textWorkspace(["type": "text", "workspace": ""]))
        XCTAssertNil(PushPayload.textWorkspace(["type": "text", "workspace": 7]))
        XCTAssertNil(PushPayload.messageId(["type": "text", "text_id": "m_x", "workspace": "ws_1"]))
    }

    func testTextTapOpensTheWorkspaceMessages() async {
        let model = AppModel(useMock: true)
        AppDelegate.model = model
        AppDelegate.handleTap(textWorkspace: MockRelay.pilatus)
        XCTAssertEqual(model.tab, .chats)
        XCTAssertEqual(model.path, [.workspace(MockRelay.pilatus)])
        XCTAssertNil(model.focusedQuestion)
        AppDelegate.model = nil
    }

    func testTextTapBeforeModelExistsIsKept() {
        AppDelegate.model = nil
        AppDelegate.handleTap(textWorkspace: MockRelay.reports)
        XCTAssertEqual(AppDelegate.pendingText, MockRelay.reports)
        let model = AppModel(useMock: true)
        AppDelegate.model = model
        XCTAssertNil(AppDelegate.pendingText)
        XCTAssertEqual(model.path, [.workspace(MockRelay.reports)])
        AppDelegate.model = nil
    }
}

final class SettingsBugFixTests: XCTestCase {
    func testSignOutTextNamesWaitingWork() {
        XCTAssertEqual(SignOutWording.text(messages: 0, answers: 0), SignOutWording.base)
        XCTAssertEqual(SignOutWording.text(messages: 2, answers: 0), SignOutWording.base + " 2 messages are still waiting to be sent and will be lost.")
        XCTAssertEqual(SignOutWording.text(messages: 0, answers: 1), SignOutWording.base + " 1 answer is still waiting to be sent and will be lost.")
        XCTAssertEqual(SignOutWording.text(messages: 1, answers: 2), SignOutWording.base + " 1 message and 2 answers are still waiting to be sent and will be lost.")
    }

    func testSignOutTextCountsOnlyUnsentItems() {
        let waiting = OutboxItem(clientId: "a", phone: "p", kind: .send, workspace: "w", createdAt: "2026-11-12T10:00:00Z")
        var stored = OutboxItem(clientId: "b", phone: "p", kind: .send, workspace: "w", createdAt: "2026-11-12T10:00:00Z")
        stored.sentMessageId = "m_1"
        var refused = OutboxItem(clientId: "c", phone: "p", kind: .answer, workspace: "w", createdAt: "2026-11-12T10:00:00Z")
        refused.failure = "Not sent"
        XCTAssertEqual(SignOutWording.text(for: []), SignOutWording.base)
        XCTAssertEqual(SignOutWording.text(for: [stored]), SignOutWording.base)
        XCTAssertEqual(SignOutWording.text(for: [waiting, stored, refused]), SignOutWording.base + " 1 message and 1 answer are still waiting to be sent and will be lost.")
    }

    func testNotificationAccessFromSystemStatus() {
        XCTAssertEqual(NotificationAccess.from(.denied), .denied)
        XCTAssertEqual(NotificationAccess.from(.notDetermined), .notAsked)
        XCTAssertEqual(NotificationAccess.from(.authorized), .allowed)
        XCTAssertEqual(NotificationAccess.from(.provisional), .allowed)
        XCTAssertEqual(NotificationAccess.from(.ephemeral), .allowed)
    }
}
