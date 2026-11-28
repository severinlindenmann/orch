import SwiftUI
import XCTest
@testable import OrchMobile

/// ORCH-1942: the "Not sent" bubble says why (when the phone knows) and what to do, per bubble, and keeps saying it.
/// Model and rule tests on the mock relay (no screen needed); the one hosted view checks large text.
@MainActor
final class NotSentBubbleTests: XCTestCase {
    private var dir: URL!
    private let gen = ConversationID.general(workspace: MockRelay.pilatus)
    override func setUp() async throws { Keychain.delete(); dir = FileManager.default.temporaryDirectory.appendingPathComponent("ns-" + UUID().uuidString); UserDefaults.standard.removeObject(forKey: "chatRead") }
    override func tearDown() async throws { Keychain.delete(); try? FileManager.default.removeItem(at: dir); UserDefaults.standard.removeObject(forKey: "chatRead") }
    private func paired() async -> AppModel {
        let m = AppModel(useMock: true, voiceMode: .scripted, outboxDirectory: dir, speechCache: dir.appendingPathComponent("sp"), systemAudioControls: false)
        m.openSampleInvite(); await m.connect(phoneName: "T"); await m.finishSetup(allowNotifications: false); return m
    }
    private func receipt(_ m: AppModel, _ text: String) -> Receipt? { m.conversationItems(gen).first { $0.text == text }?.receipt }
    private func clientId(_ m: AppModel, _ text: String) throws -> String { try XCTUnwrap(m.outbox.items.first { $0.text == text }?.clientId) }

    /// Two bubbles refused for different reasons each keep their own sentence, also after the banner on Chats is gone.
    func testTwoBubblesEachKeepTheirOwnReason() async throws {
        let m = await paired()
        await m.mock!.queueSendFailures([404, 422])
        _ = try await m.send(MessageDraft(text: "with a file"), to: .general(workspace: MockRelay.pilatus))
        _ = try await m.send(MessageDraft(text: "plain"), to: .general(workspace: MockRelay.pilatus))
        XCTAssertEqual(receipt(m, "with a file"), .failed(NotSentNote.text(status: 404)))
        XCTAssertEqual(receipt(m, "plain"), .failed(NotSentNote.generic))
        XCTAssertNotEqual(NotSentNote.text(status: 404), NotSentNote.generic)
        m.message = nil   // the transient line on Chats is dismissed
        XCTAssertEqual(receipt(m, "with a file"), .failed(NotSentNote.text(status: 404)), "the bubble keeps the reason")
        XCTAssertEqual(receipt(m, "plain"), .failed(NotSentNote.generic))
        for item in m.conversationItems(gen) {
            if case .failed(let why)? = item.receipt { XCTAssertFalse(why.contains("Try again later."), "never the relay's own text") }
        }
    }

    /// Discard takes away only the bubble it was tapped on.
    func testDiscardRemovesOnlyThatBubble() async throws {
        let m = await paired()
        await m.mock!.queueSendFailures([422, 422])
        _ = try await m.send(MessageDraft(text: "first"), to: .general(workspace: MockRelay.pilatus))
        _ = try await m.send(MessageDraft(text: "second"), to: .general(workspace: MockRelay.pilatus))
        m.discardSend(try clientId(m, "first"))
        XCTAssertNil(receipt(m, "first"), "the discarded bubble is gone")
        XCTAssertEqual(receipt(m, "second"), .failed(NotSentNote.generic), "the other one stays Not sent")
        XCTAssertEqual(m.outbox.items.filter { $0.failure != nil }.map(\.text), ["second"])
    }

    /// Retry sends only the one picked; when it is refused again the bubble says the new reason, and VoiceOver hears it once.
    func testRetryRefusedAgainSaysTheNewReason() async throws {
        let m = await paired()
        await m.mock!.queueSendFailures([422, 422])
        _ = try await m.send(MessageDraft(text: "first"), to: .general(workspace: MockRelay.pilatus))
        _ = try await m.send(MessageDraft(text: "second"), to: .general(workspace: MockRelay.pilatus))
        await m.mock!.queueSendFailures([403])
        await m.retrySend(try clientId(m, "first"))
        XCTAssertEqual(receipt(m, "first"), .failed(NotSentNote.text(status: 403)))
        XCTAssertEqual(receipt(m, "second"), .failed(NotSentNote.generic), "the other bubble was not sent again")
        XCTAssertEqual(m.announcement, NotSentNote.spoken(NotSentNote.text(status: 403)))
        XCTAssertEqual(m.message, NotSentNote.banner(workspace: m.workspace(MockRelay.pilatus).map { displayName($0.name) }))
        let again = await m.mock!.requests.filter { $0.text == "second" }
        XCTAssertTrue(again.isEmpty)
    }

    /// Offline is waiting, never Not sent: a retry without a connection shows the clock and the wait line, then goes out by itself.
    func testRetryWhileOfflineWaitsInsteadOfFailing() async throws {
        let m = await paired()
        await m.mock!.queueSendFailures([422])
        _ = try await m.send(MessageDraft(text: "later"), to: .general(workspace: MockRelay.pilatus))
        XCTAssertEqual(receipt(m, "later"), .failed(NotSentNote.generic))
        XCTAssertNil(QueuedNote.text(for: m.outbox.items.first { $0.text == "later" }), "Not sent shows no wait line")
        await m.mock!.setOffline(true)
        await m.retrySend(try clientId(m, "later"))
        XCTAssertEqual(receipt(m, "later"), .queued, "no connection: the clock, not Not sent")
        XCTAssertEqual(QueuedNote.text(for: m.outbox.items.first { $0.text == "later" }), QueuedNote.waiting)
        XCTAssertNotEqual(m.announcement, NotSentNote.spoken(NotSentNote.generic))
        await m.mock!.setOffline(false)
        await m.flushOutbox()
        let after = receipt(m, "later")
        XCTAssertNotEqual(after, .queued); XCTAssertNotEqual(after, .failed(NotSentNote.generic))
    }

    /// VoiceOver: "Not sent" and the sentence, once, for every refusal; the words are the ones on the bubble.
    func testVoiceOverLabelSaysNotSentAndTheSentenceOnce() {
        for status in [nil, 400, 403, 404, 409, 413, 422] as [Int?] {
            let note = NotSentNote.text(status: status), spoken = NotSentNote.spoken(note)
            XCTAssertEqual(spoken, "Not sent. " + note)
            XCTAssertEqual(spoken.components(separatedBy: "Not sent").count, 2, "said once")
            XCTAssertTrue(note.hasSuffix("."), "a whole sentence")
            XCTAssertFalse(note.isEmpty)
        }
        var item = OutboxItem(clientId: "c1", phone: "ph_1", kind: .send, workspace: MockRelay.pilatus, createdAt: "2026-11-28T09:00:00Z")
        item.failure = "This phone may not reach that workspace."; item.failureStatus = 403
        XCTAssertEqual(NotSentNote.text(for: item), NotSentNote.text(status: 403))
        XCTAssertFalse(NotSentNote.spoken(NotSentNote.text(for: item)).contains("may not reach"), "never the relay's own text")
        XCTAssertEqual(NotSentNote.banner(workspace: "Pilatus"), "A message to Pilatus was not sent. Open the chat to retry it.")
        XCTAssertEqual(NotSentNote.banner(workspace: nil), "A message was not sent. Open the chat to retry it.")
    }

    /// Large text: the sentence wraps onto more lines inside the bubble's width instead of being cut, and Retry / Discard keep 44 pt.
    func testLargeTextWrapsTheSentence() {
        let width: CGFloat = 260
        func height(_ size: DynamicTypeSize) -> CGFloat {
            let view = ReceiptView(receipt: .failed(NotSentNote.text(status: 403)), time: "10:02", onRetry: {}, onDiscard: {})
                .environment(\.dynamicTypeSize, size).frame(width: width)
            let fit = UIHostingController(rootView: view).sizeThatFits(in: CGSize(width: width, height: .greatestFiniteMagnitude))
            XCTAssertLessThanOrEqual(fit.width, width + 0.5, "stays inside the bubble at \(size)")
            return fit.height
        }
        let normal = height(.large), big = height(.accessibility5)
        XCTAssertGreaterThanOrEqual(normal, 44, "Retry and Discard are 44 pt tall")
        XCTAssertGreaterThan(big, normal, "larger text takes more lines; nothing is cut")
    }
}
