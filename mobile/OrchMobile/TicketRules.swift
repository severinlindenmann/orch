import Foundation
import SwiftUI

extension ConversationRules {
    static func needsYouText(position n: Int, of total: Int) -> String {
        total > 1 ? "Needs your OK · \(n) of \(total)" : "Needs your OK"
    }

    static func openPosition(of id: String, in items: [ConvItem]) -> (n: Int, of: Int)? {
        let open = items.indices.filter {
            items[$0].kind == .question && items[$0].question?.isMakeTicket != true && items[$0].answer == nil && !isStale(index: $0, in: items)
        }
        guard let position = open.firstIndex(where: { items[$0].id == id }) else { return nil }
        return (position + 1, open.count)
    }

    static func answeredText(in items: [ConvItem]) -> String? {
        let questions = items.indices.filter { items[$0].kind == .question && items[$0].question?.isMakeTicket != true && !isStale(index: $0, in: items) }
        guard !questions.isEmpty else { return nil }
        let answered = questions.filter { items[$0].answer != nil }.count
        return "\(answered) of \(questions.count) answered"
    }
}

struct ArtifactMention: Equatable {
    let range: Range<String.Index>
    let attachmentId: String
}

enum ArtifactMentions {
    static func attributed(_ text: String, attachments: [TicketSnapshot.Attachment]) -> AttributedString {
        var attributed = AttributedString(text)
        for mention in mentions(in: text, attachments: attachments) {
            if let range = Range(mention.range, in: attributed),
               let encoded = mention.attachmentId.addingPercentEncoding(withAllowedCharacters: .alphanumerics),
               let url = URL(string: "orch-artifact://" + encoded) {
                attributed[range].link = url
                attributed[range].foregroundColor = Theme.brand
                attributed[range].underlineStyle = .single
            }
        }
        return attributed
    }

    static func attachmentId(from url: URL) -> String? {
        guard url.scheme == "orch-artifact" else { return nil }
        return String(url.absoluteString.dropFirst("orch-artifact://".count)).removingPercentEncoding
    }

    static func mentions(in text: String, attachments: [TicketSnapshot.Attachment]) -> [ArtifactMention] {
        let punctuation = Set(".,;:!?()[]\"'`")
        // Nothing to point at, or a huge text: no per-word work at all.
        let files = attachments.filter { $0.kind != "link" }
        guard !files.isEmpty, text.utf8.count <= 20_000 else { return [] }
        let names = files.map { attachment in
            (id: attachment.id, names: [attachment.name, attachment.label].compactMap { $0?.lowercased() }.filter { !$0.isEmpty })
        }
        return text.split(whereSeparator: { $0.isWhitespace }).compactMap { word in
            var start = word.startIndex
            var end = word.endIndex
            while start < end && punctuation.contains(text[start]) { start = text.index(after: start) }
            while start < end && punctuation.contains(text[text.index(before: end)]) { end = text.index(before: end) }
            let candidate = String(text[start..<end]).lowercased()
            guard candidate.contains("."), !candidate.contains("://"), !candidate.hasPrefix("//"),
                  URL(string: candidate)?.scheme == nil else { return nil }
            guard candidate.range(of: #"\.[\p{L}\p{N}]+"#, options: .regularExpression) != nil else { return nil }
            // An exact name wins over a path-suffix match that happens to come first.
            let match = names.first { $0.names.contains(candidate) } ?? names.first { file in
                file.names.contains { candidate.hasSuffix("/" + $0) || $0.hasSuffix("/" + candidate) }
            }
            guard let match else { return nil }
            return ArtifactMention(range: start..<end, attachmentId: match.id)
        }
    }
}

enum QueuedNote {
    static let waiting = "Waiting · will send when online"
    static func text(for item: OutboxItem?) -> String? {
        guard let item, item.sentMessageId == nil, item.failure == nil else { return nil }
        return ThrottleNote.text(for: item) ?? waiting
    }
}
