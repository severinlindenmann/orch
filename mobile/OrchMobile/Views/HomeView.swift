import SwiftUI

struct HomeView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var expandedTags: Set<String> = []
    @State private var showWorkspaces = false
    @State private var openTicket: Ticket?

    private var greeting: String {
        switch Calendar.current.component(.hour, from: Date()) {
        case 5..<12: "Good morning"
        case 12..<18: "Good afternoon"
        default: "Good evening"
        }
    }

    private var subtitle: String {
        let n = model.tickets(.needsYou).count
        if n > 0 { return "\(n == 1 ? "One ticket needs" : "\(n) tickets need") you." }
        switch model.connection {
        case .ok: return "All clear. Nothing needs you right now."
        case .unreachable: return "Can't reach your workspaces."
        case .checking: return "Checking for questions…"
        }
    }

    @Environment(\.dynamicTypeSize) private var dynamicType  // re-evaluate fonts when text size changes (no view-identity reset)
    var body: some View {
        let _ = dynamicType
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Brand().padding(.bottom, 28)
                Eyebrow(text: greeting.uppercased(), color: Theme.brand).padding(.bottom, 12)
                ScreenHeading(title: "Your tickets.", subtitle: subtitle)
                if let when = model.lastUpdatedText { Text(when).themeFont(12).foregroundStyle(Theme.muted).padding(.top, 6) }
                if !model.hasLoaded && model.message == nil {
                    ForEach(0..<2, id: \.self) { _ in
                        ticketRow(Ticket(id: "x", workspace: "x", workspaceName: "Workspace", ticket: nil, title: "Ticket title goes here",
                                         text: "", status: .working, kind: "working", at: "", question: nil))
                    }.skeleton(true).accessibilityHidden(true).padding(.top, 20)
                }
                ForEach([Ticket.Status.needsYou, .working, .done], id: \.self) { status in
                    let rows = model.tickets(status)
                    if !rows.isEmpty {
                        HStack { Eyebrow(text: status.title.uppercased()); Spacer(); Eyebrow(text: "\(rows.count)") }
                            .padding(.top, 28).padding(.bottom, 4)
                        ForEach(rows) { ticketRow($0) }
                    }
                }
                if model.hasLoaded && model.tickets.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("No tickets yet").themeFont(15, .semibold)
                        Text("Ask a workspace for something with the Ask tab. It shows up here.")
                            .themeFont(13).foregroundStyle(Theme.muted)
                        checkAgain
                    }.orchCard().padding(.top, 26)
                }
                DisclosureGroup(isExpanded: $showWorkspaces) {
                    if !model.hasLoaded && model.workspaces.isEmpty && model.message == nil {
                        ForEach(0..<2, id: \.self) { _ in
                            workspaceRow(Workspace(id: "x", name: "Workspace name", description: "What this workspace does", tags: [], online: true, lastSeen: nil, openQuestions: 0))
                        }.skeleton(true).accessibilityHidden(true)
                    }
                    ForEach(model.workspaces) { workspace in workspaceRow(workspace) }
                    if model.workspaces.isEmpty && model.hasLoaded {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("No workspaces yet").themeFont(15, .semibold)
                            Text("Ask the person who invited you to add a workspace. It will show up here.")
                                .themeFont(13).foregroundStyle(Theme.muted)
                            checkAgain
                        }.orchCard()
                    }
                } label: {
                    Text("Workspaces (\(model.workspaces.count))").themeFont(13, .semibold).foregroundStyle(Theme.muted)
                        .frame(minHeight: 44, alignment: .leading)
                }.tint(Theme.muted).padding(.top, 28).accessibilityIdentifier("workspaces-toggle")
                ModelMessage().padding(.top, 12)
            }.padding(.horizontal, 23).padding(.top, 6).padding(.bottom, 20)
        }.refreshable { await model.refresh() }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: model.tickets)
            .sheet(item: $openTicket) { TicketView(ticket: $0).presentationDetents([.large]) }
    }

    private var checkAgain: some View {
        Button { Task { await model.refresh() } } label: {
            Text(model.isLoading ? "Checking…" : "Check again").themeFont(13, .semibold).foregroundStyle(Theme.brand)
                .frame(minWidth: 120, minHeight: 44, alignment: .leading).contentShape(Rectangle())
        }.buttonStyle(PressStyle()).disabled(model.isLoading)
    }

    private func ticketRow(_ t: Ticket) -> some View {
        Button {
            if let q = t.question { model.openQuestion(messageId: q.id) } else { openTicket = t }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: t.symbol).themeFont(20)
                    .foregroundStyle(t.status == .needsYou ? Theme.warn : t.status == .working ? Theme.muted : (t.kind == "result" ? Theme.brand : Theme.danger))
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 3) {
                    Text(t.title).themeFont(14, .medium).multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                    Text("\(t.workspaceName) · \(t.stateLine)").themeFont(12).foregroundStyle(Theme.muted)
                        .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                }.frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: "chevron.right").themeFont(12).foregroundStyle(Theme.muted)
            }.frame(minHeight: 44).padding(.vertical, 12).contentShape(Rectangle())
        }.buttonStyle(PressStyle())
            .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(t.status.title): \(t.title), \(t.workspaceName), \(t.stateLine)")
            .accessibilityAddTraits(.isButton)
            .accessibilityIdentifier("ticket-\(t.id)")
    }

    private func workspaceRow(_ workspace: Workspace) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 0) {
                Button {
                    model.questionFilter = workspace.id; model.tab = .questions
                } label: {
                    HStack(spacing: 10) {
                        Text(String(workspace.displayName.prefix(1))).themeFont(14)
                            .frame(width: 35, height: 35).foregroundStyle(Theme.brand)
                            .background(Theme.brand.opacity(0.1), in: RoundedRectangle(cornerRadius: 9))
                        VStack(alignment: .leading, spacing: 3) {
                            Text(workspace.displayName).themeFont(14, .medium).fixedSize(horizontal: false, vertical: true)
                            if let description = workspace.description {
                                Text(description).themeFont(12).foregroundStyle(Theme.muted)
                            }
                            HStack(spacing: 4) {
                                Circle().fill(workspace.online ? Theme.brand : Theme.muted).frame(width: 5, height: 5)
                                Text(lastSeenText(workspace.lastSeen, online: workspace.online)).foregroundStyle(Theme.muted)
                            }.themeFont(12)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        if workspace.openQuestions > 0 {
                            Text("\(workspace.openQuestions)").themeFont(11).foregroundStyle(Theme.brand)
                                .padding(.horizontal, 7).padding(.vertical, 2)
                                .background(Theme.brand.opacity(0.1), in: RoundedRectangle(cornerRadius: 5))
                        }
                    }.frame(minHeight: 44).contentShape(Rectangle())
                }.buttonStyle(PressStyle())
                Button {
                    if expandedTags.contains(workspace.id) { expandedTags.remove(workspace.id) }
                    else { expandedTags.insert(workspace.id) }
                } label: {
                    Image(systemName: expandedTags.contains(workspace.id) ? "chevron.up" : "chevron.down")
                        .themeFont(12).frame(width: 44, height: 44)
                }.foregroundStyle(Theme.muted).accessibilityLabel("Tags for \(workspace.displayName)")
                    .accessibilityValue(expandedTags.contains(workspace.id) ? "Expanded" : "Collapsed")
                    .accessibilityIdentifier("tags-\(workspace.id)")
            }
            if expandedTags.contains(workspace.id) {
                Text(workspace.tags.joined(separator: " · ")).themeFont(11).foregroundStyle(Theme.muted)
                    .padding(.leading, 45)
            }
        }.padding(.vertical, 17)
            .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
    }
}
