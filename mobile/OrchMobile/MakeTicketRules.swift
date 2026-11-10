import Foundation

enum MakeTicketRules {
    enum CardState: Equatable {
        case open, making, waiting, made(key: String?), failed, closed(notNow: Bool)
    }

    static func state(answer: String?, answeredAt: Date?, results: [ProposalResult], now: Date,
                      workspaceLive: Bool) -> CardState {
        if let made = results.first(where: { $0.result == "made" }) { return .made(key: made.key) }
        if let last = results.last {
            if last.result == "refused" { return .failed }
            if last.result == "decided" {
                return last.key.map { .made(key: $0) } ?? .closed(notNow: false)
            }
        }
        if answer == "not_now" { return .closed(notNow: true) }
        if answer == "make" {
            return !workspaceLive || now.timeIntervalSince(answeredAt ?? now) >= 120 ? .waiting : .making
        }
        return .open
    }
}
