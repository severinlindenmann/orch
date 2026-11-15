import CryptoKit
import Foundation
import UIKit

/// Fixture for `-mockReviewStack YES`: 8 stack questions of the Pilatus workspace (3 drafts incl. one compare, 2 choices, 2 checks,
/// 1 plan) with fake blobs whose size and sha256 match the cards. One check needs the computer's signature (signs: true).
enum MockReviewStack {
    struct Blob { let data: Data; let name: String; let mime: String }
    private static let ws = MockRelay.pilatus

    private static func png(_ color: UIColor, _ label: String) -> Data {
        UIGraphicsImageRenderer(size: CGSize(width: 160, height: 100)).pngData { c in
            color.setFill(); c.fill(CGRect(x: 0, y: 0, width: 160, height: 100))
            (label as NSString).draw(at: CGPoint(x: 12, y: 40), withAttributes: [.foregroundColor: UIColor.white, .font: UIFont.boldSystemFont(ofSize: 18)])
        }
    }
    private static func hex(_ d: Data) -> String { SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined() }

    /// blob id -> bytes. Built once.
    static let blobs: [String: Blob] = {
        var b: [String: Blob] = [:]
        func img(_ id: String, _ name: String, _ c: UIColor) { b[id] = Blob(data: png(c, name), name: name, mime: "image/png") }
        img("b_rv1f0", "invoice.png", .systemBlue)
        img("b_rv3f0", "before.png", .systemGray); img("b_rv3f1", "after.png", .systemGreen)
        img("b_rv4fa", "logo-a.png", .systemRed); img("b_rv4fb", "logo-b.png", .systemOrange); img("b_rv4fc", "logo-c.png", .systemPurple)
        b["b_rv6f0"] = Blob(data: Data("<h1>Fish test page</h1>".utf8), name: "page.html", mime: "text/html")
        return b
    }()

    private static func files(_ ids: [String]) -> [CardFile]? {
        let f = ids.compactMap { id in blobs[id].map { CardFile(blobId: id, name: $0.name, size: $0.data.count, sha256: hex($0.data), mime: $0.mime) } }
        return f.isEmpty ? nil : f
    }
    static func digest(_ id: String) -> String { hex(Data(id.utf8)) }

    private static func question(_ n: Int, qid: String, ticket: String, key: String, title: String, text: String, card: ReviewCard,
                                 files ids: [String] = [], review: Bool = false, options: [String] = []) -> Question {
        let id = "m_rvstack\(String(format: "%08d", n))"
        return Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: ws, to: "phones", type: "question",
            createdAt: "2026-11-15T09:0\(n):00Z", ticket: ticket,
            body: QuestionBody(questionId: qid, title: title, text: text, options: options, recommended: nil, review: review ? true : nil,
                               digest: digest(id), card: card, cardFiles: files(ids)), key: key), workspaceName: "Pilatus Workspace")
    }
    static func questionId(_ n: Int) -> String { "m_rvstack\(String(format: "%08d", n))" }

    static var questions: [Question] {
        [
            question(1, qid: "q1", ticket: "t_rv1", key: "RV-1", title: "Invoices", text: "Send the November invoice to Anna",
                     card: ReviewCard(kind: .draft, title: "Send the November invoice to Anna", then: "The helper sends the PDF to anna@pilatus.ch.",
                                      why: "She asked for it by Friday.", okLabel: "Send it", preview: .img(src: .file(0), alt: "Invoice, page 1")), files: ["b_rv1f0"]),
            question(2, qid: "q2", ticket: "t_rv2", key: "RV-2", title: "Landlord", text: "Reply to the landlord",
                     card: ReviewCard(kind: .draft, title: "Reply to the landlord", then: "The helper sends this reply.",
                                      preview: .doc(heading: "Re: heating", paras: ["Thank you for the quick answer."], steps: []))),
            question(3, qid: "q3", ticket: "t_rv3", key: "RV-3", title: "Website", text: "Use the new header",
                     card: ReviewCard(kind: .draft, title: "Use the new header", then: "The helper publishes the page.", okLabel: "Publish",
                                      preview: .compare(before: .img(src: .file(0), alt: "Before"), after: .img(src: .file(1), alt: "After"), note: "Header only")),
                     files: ["b_rv3f0", "b_rv3f1"]),
            question(4, qid: "q4", ticket: "t_rv4", key: "RV-4", title: "Logo", text: "Pick a logo",
                     card: ReviewCard(kind: .choice, title: "Pick a logo", then: "The helper uses your pick everywhere.", preview: .options([
                        CardOption(id: "A", title: "Round", preview: .img(src: .file(0), alt: nil)),
                        CardOption(id: "B", title: "Square", preview: .img(src: .file(1), alt: nil)),
                        CardOption(id: "C", title: "Wordmark", text: "Only the name, no symbol.", preview: .img(src: .file(2), alt: nil))])),
                     files: ["b_rv4fa", "b_rv4fb", "b_rv4fc"]),
            question(5, qid: "q5", ticket: "t_rv5", key: "RV-5", title: "Meeting", text: "Which day for the meeting?",
                     card: ReviewCard(kind: .choice, title: "Which day for the meeting?", then: "The helper invites everyone.", preview: .options([
                        CardOption(id: "A", title: "Tuesday"), CardOption(id: "B", title: "Thursday")]))),
            question(6, qid: "review-1", ticket: "t_rv6", key: "RV-6", title: "Fish test page", text: "Is this done?",
                     card: ReviewCard(kind: .check, title: "Fish test page", then: "The ticket moves to Done.", preview: .page(src: .file(0))),
                     files: ["b_rv6f0"], review: true, options: ["accept", "changes"]),
            question(7, qid: "review-1", ticket: "t_rv7", key: "RV-7", title: "Deploy to production", text: "Is this done?",
                     card: ReviewCard(kind: .check, title: "Deploy to production", then: "The helper keeps the release.", signs: true),
                     review: true, options: ["accept", "changes"]),
            question(8, qid: "q8", ticket: "t_rv8", key: "RV-8", title: "Backup plan", text: "Backup plan",
                     card: ReviewCard(kind: .plan, title: "Backup plan", then: "The helper starts at step 1.", okLabel: "Start",
                                      preview: .doc(heading: nil, paras: [], steps: ["Copy the files", "Check the copy", "Delete the old files"]))),
        ]
    }
}
