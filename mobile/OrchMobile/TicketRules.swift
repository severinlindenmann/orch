import Foundation

extension ConversationRules {
    static func needsYouText(position n: Int, of total: Int) -> String {
        total > 1 ? "Needs you · \(n) of \(total)" : "Needs you"
    }

    static func openPosition(of id: String, in items: [ConvItem]) -> (n: Int, of: Int)? {
        let open = items.indices.filter {
            items[$0].kind == .question && items[$0].answer == nil && !isStale(index: $0, in: items)
        }
        guard let position = open.firstIndex(where: { items[$0].id == id }) else { return nil }
        return (position + 1, open.count)
    }

    static func answeredText(in items: [ConvItem]) -> String? {
        let questions = items.indices.filter { items[$0].kind == .question && !isStale(index: $0, in: items) }
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
    static func mentions(in text: String, attachments: [TicketSnapshot.Attachment]) -> [ArtifactMention] {
        let punctuation = Set(".,;:!?()[]\"'`")
        return text.split(whereSeparator: { $0.isWhitespace }).compactMap { word in
            var start = word.startIndex
            var end = word.endIndex
            while start < end && punctuation.contains(text[start]) { start = text.index(after: start) }
            while start < end && punctuation.contains(text[text.index(before: end)]) { end = text.index(before: end) }
            let candidate = String(text[start..<end]).lowercased()
            guard candidate.range(of: #"\.[\p{L}\p{N}]+"#, options: .regularExpression) != nil else { return nil }
            let match = attachments.first { attachment in
                guard attachment.kind != "link" else { return false }
                return [attachment.name, attachment.label].compactMap { $0 }.contains { value in
                    let name = value.lowercased()
                    return !name.isEmpty && (candidate == name || candidate.hasSuffix("/" + name) || name.hasSuffix("/" + candidate))
                }
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
