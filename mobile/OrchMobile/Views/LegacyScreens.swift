import SwiftUI

// Screens that M1 (NewChatView/NewTopicView) and M3 (ChatInfoView) replace. Delete the matching type here when yours lands.

/// Chat info: details and the media, links and files kept with a ticket (or the whole workspace).
struct ChatInfoView: View {
    @Environment(AppModel.self) private var model
    let workspaceId: String
    let ticketId: String?
    @State private var tab = 0

    var body: some View {
        let w = model.workspace(workspaceId)
        let t = ticketId.flatMap { model.ticket(workspaceId, $0) }
        let wsTickets = model.tickets.filter { $0.workspace == workspaceId && $0.ticket != nil }
        let atts: [TicketSnapshot.Attachment] = (t.map { [$0] } ?? wsTickets).flatMap { $0.view?.attachments ?? [] }
        let media = atts.filter { $0.kind == "image" }, links = atts.filter { $0.kind == "link" }, files = atts.filter { $0.kind == "file" }
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let t {
                    Text(t.displayTitle).themeFont(24, .semibold)
                    HStack { KeyTag(key: t.key); StatusPill(status: t.status, kind: t.kind) }
                    if let a = t.view?.agent { detail("Agent", a) }
                    detail("Workspace", w?.displayName ?? t.workspaceName)
                    detail("Updated", ChatBuilder.timeText(t.at))
                    if let s = t.view?.summary ?? Optional(t.text), !s.isEmpty {
                        VStack(alignment: .leading, spacing: 4) { Eyebrow(text: "WHERE IT STANDS"); Text(s).themeFont(15) }
                            .padding(.leading, 12).overlay(alignment: .leading) { Rectangle().fill(Theme.brand).frame(width: 3) }
                    }
                } else {
                    Avatar(name: w?.displayName ?? "W", size: 52)
                    Text(w?.displayName ?? "Workspace").themeFont(24, .semibold)
                    Text(w.map { lastSeenText($0.lastSeen, online: $0.online) } ?? "").themeFont(14).foregroundStyle(Theme.muted)
                    if let d = w?.description { Text(d).themeFont(15) }
                    Eyebrow(text: "\(wsTickets.count) TICKETS")
                    ForEach(wsTickets) { x in
                        HStack(spacing: 8) { KeyTag(key: x.key); Text(x.displayTitle).themeFont(14).lineLimit(1); Spacer(); StatusPill(status: x.status, kind: x.kind) }
                    }
                }
                Picker("", selection: $tab) {
                    Text("Media \(media.count)").tag(0); Text("Links \(links.count)").tag(1); Text("Files \(files.count)").tag(2)
                }.pickerStyle(.segmented).accessibilityIdentifier("info-tabs")
                let shown = [media, links, files][tab]
                if shown.isEmpty { Text("Nothing here yet.").themeFont(14).foregroundStyle(Theme.muted) }
                else if tab == 0 {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 8)], spacing: 8) { ForEach(shown) { AttachmentTile(attachment: $0) } }
                } else {
                    ForEach(shown) { AttachmentTile(attachment: $0).padding(.vertical, 4) }
                }
            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
        }.background(Theme.bg.ignoresSafeArea()).navigationTitle("Chat info").navigationBarTitleDisplayMode(.inline)
    }

    private func detail(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) { Text(label).themeFont(12).foregroundStyle(Theme.muted); Text(value).themeFont(15) }
    }
}

