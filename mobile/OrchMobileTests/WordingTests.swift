import XCTest
@testable import OrchMobile

/// Owner words 5A/6A/10A: "Needs you", "Ready for review", "Not started". The old phrases must not come back anywhere in the app.
final class WordingTests: XCTestCase {
    private let banned = ["Waiting on you", "Waiting for your answer", "Check this", "Backlog"]

    func testStatusWordsAreTheOwnerWords() {
        XCTAssertEqual(TopicStatus.waitingOnYou.label, "Needs you"); XCTAssertEqual(TopicStatus.waitingOnYou.chip, "Needs you")
        XCTAssertEqual(TopicStatus.review.label, "Ready for review"); XCTAssertEqual(TopicStatus.review.chip, "Ready for review")
        XCTAssertEqual(TopicStatus.backlog.label, "Not started"); XCTAssertEqual(TopicStatus.backlog.chip, "Not started")
        var words = TopicStatus.allCases.flatMap { [$0.label, $0.chip] }
        words += [Ticket.Status.needsYou, .review, .working, .backlog, .done].map(\.title)
        for w in words { for b in banned { XCTAssertFalse(w.contains(b), "\(w) contains \(b)") } }
    }

    func testNoOldPhraseInTheAppSources() throws {
        let dir = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("OrchMobile")
        let files = FileManager.default.enumerator(at: dir, includingPropertiesForKeys: nil)?.compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" } ?? []
        try XCTSkipIf(files.isEmpty, "sources not readable from the test host")
        for f in files {
            let text = try String(contentsOf: f, encoding: .utf8)
            for b in banned where b != "Backlog" { XCTAssertFalse(text.contains(b), "\(f.lastPathComponent) says \"\(b)\"") }
            XCTAssertFalse(text.contains("\"Backlog\""), "\(f.lastPathComponent) shows Backlog")
        }
    }
}
