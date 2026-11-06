import XCTest
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
