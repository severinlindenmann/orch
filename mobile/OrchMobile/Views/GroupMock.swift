import Foundation

/// Opt-in fixture shared by MockRelay and the group view tests.
enum GroupMock {
    static let finance = "ws_finance001", home = "ws_home000001", bank = "ws_bank000001"
    static let ticket = "t_cartax2027"
    static let names = [finance: "Finance", home: "Home", bank: "Bank"]

    static func question(at: String) -> Question {
        Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_groupallow00001", from: bank, to: "phones", type: "question",
            createdAt: at, ticket: "t_banktax001",
            body: QuestionBody(questionId: "relay:allow", title: "Check last year's payment",
                               text: "Bank: let Finance give tasks?", options: ["once", "always", "no"], recommended: nil, scope: "tasks from Finance", allowQuestion: true, groupRef: GroupRef(host: finance, id: "grp_" + ticket)), key: "BANK-3"), workspaceName: "Bank")
    }

    static func messages(now: Date = Date()) -> [PhoneMessage] {
        let members = [finance, home, bank].map { GroupMember(ws: $0, name: names[$0] ?? "Workspace") }
        let formatter = ISO8601DateFormatter()
        func copy(_ seq: Int, _ text: String = "", by: String = finance, kind: String? = nil,
                  event: GroupEvent? = nil, task: GroupTask? = nil, file: Bool = false,
                  closed: Bool = false) -> PhoneMessage {
            let at = formatter.string(from: now.addingTimeInterval(Double(seq - 10) * 20))
            let t = closed ? "t_cartax2026" : ticket
            let title = closed ? "Pay car tax 2026" : "Pay car tax 2027"
            let id = "m_group\(closed ? "done" : "copy")\(String(format: "%05d", seq))"
            let phone = by == "you"
            let origin = phone ? "ph_iphone0001" : by
            let view: TicketSnapshot? = file ? TicketSnapshot(title: title, attachments: [
                .init(kind: "image", title: "Car tax letter", blobId: "b_0123456789abcdef", name: "car-tax-letter.png", size: 48_000)
            ]) : nil
            return PhoneMessage(message: TextMessage(id: id, from: finance, to: "phones", type: "text", createdAt: at, ticket: t,
                body: TextBody(text: text, update: kind.map { TextUpdate(kind: $0) }, ticketView: view,
                               group: GroupInfo(id: "grp_" + t, host: finance, title: title, members: members, seq: seq),
                               groupEvent: event, by: by, via: phone ? "phone" : nil, phone: phone ? origin : nil,
                               origin: GroupOrigin(id: "origin_" + id, from: origin, at: at), task: task, sharedFiles: file ? ["b_0123456789abcdef"] : nil),
                key: closed ? "FIN-8" : "FIN-14", replyTo: phone ? "m_groupcopy00001" : nil), workspaceName: "Finance")
        }
        return [
            copy(1, kind: "note", event: GroupEvent(kind: "created")),
            copy(2, "Please sort out the car tax.", by: "you"),
            copy(3, kind: "note", event: GroupEvent(kind: "member_added", ws: home, name: "Home", fromSeq: 3)),
            copy(4, "Is the 2025 car tax letter in the household files?"),
            copy(5, "I'll look in the household files.", by: home),
            copy(6, by: home, kind: "working", task: GroupTask(delegate: "d_home", ws: home, ticket: "t_hometax001", key: "HOME-7", title: "Find the 2025 car tax letter", status: "working")),
            copy(7, kind: "note", event: GroupEvent(kind: "approval_needed", ws: bank, delegate: "d_bank", questionMessage: "m_groupallow00001"), task: GroupTask(delegate: "d_bank", ws: bank, ticket: "t_banktax001", status: "waiting_approval", questionMessage: "m_groupallow00001")),
            copy(8, kind: "note", file: true),
            copy(1, kind: "note", event: GroupEvent(kind: "created"), closed: true),
            copy(2, "The car tax is paid.", closed: true),
            copy(3, kind: "note", event: GroupEvent(kind: "closed"), closed: true)
        ]
    }
}
