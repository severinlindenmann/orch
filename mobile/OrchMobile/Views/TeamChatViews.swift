import SwiftUI

/// Team chat step 2 (ORCH-1175): the strip above a ticket chat ("Pilatus, Sales and Bank" with + Add), the Add sheet
/// (Workspaces) and chat info (members, who added them and when, older orch). Words and rules: TeamChatRules.
struct TeamChatStrip: View {
    let workspace: String
    let ticket: String
    let workspaceName: String
    @Environment(AppModel.self) private var model
    @State private var addShown = false
    @State private var infoShown = false

    private var members: [GroupMember] {
        TeamChatRules.members(TeamChatRules.group(in: model.groups.groups, workspace: workspace, ticket: ticket),
                              workspace: workspace, workspaceName: workspaceName)
    }

    /// Shown once another workspace is in the chat or one of the person's other workspaces can be added.
    nonisolated static func shows(members: [GroupMember], candidates: [Workspace]) -> Bool { members.count > 1 || !candidates.isEmpty }

    var body: some View {
        let members = self.members
        if Self.shows(members: members, candidates: TeamChatRules.candidates(model.workspaces, members: members)) {
            HStack(spacing: 10) {
                Button { infoShown = true } label: {
                    HStack(spacing: 0) {
                        HStack(spacing: -6) {
                            ForEach(members.prefix(3), id: \.ws) { m in
                                WorkspaceBadge(name: m.name, icon: m.look?.icon, color: m.look?.color, size: 22)
                                    .overlay(Circle().stroke(Theme.bg, lineWidth: 2))
                            }
                        }.accessibilityHidden(true)
                        Text(TeamChatRules.stripText(members)).themeFont(13).foregroundStyle(Theme.muted)
                            .lineLimit(1).truncationMode(.tail).padding(.leading, 8)
                        Spacer(minLength: 8)
                    }.contentShape(Rectangle())
                }.buttonStyle(PressStyle()).frame(minHeight: 44)
                    .accessibilityLabel("In this chat: " + TeamChatRules.stripText(members) + ". Chat info")
                    .accessibilityIdentifier("team-chat-members")
                Button { addShown = true } label: {
                    Label("Add", systemImage: "plus").themeFont(13, .semibold).foregroundStyle(Theme.brand)
                        .padding(.horizontal, 12).frame(minHeight: 32)
                        .background(Theme.surface2, in: Capsule())
                }.buttonStyle(PressStyle()).frame(minHeight: 44)
                    .accessibilityLabel("Add to this chat").accessibilityIdentifier("team-chat-add")
            }
            .padding(.horizontal, 18)
            .fixedSize(horizontal: false, vertical: true)
            .background(Theme.bg)
            .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
            .sheet(isPresented: $addShown) {
                AddToChatSheet(workspace: workspace, ticket: ticket, workspaceName: workspaceName)
                    .presentationDetents([.medium, .large])
            }
            .sheet(isPresented: $infoShown) {
                TeamChatInfoView(workspace: workspace, ticket: ticket, workspaceName: workspaceName)
                    .presentationDetents([.medium, .large])
            }
        }
    }
}

/// "Add to this chat" with the Workspaces list (the person's own workspaces on this phone that are not in it yet).
struct AddToChatSheet: View {
    let workspace: String
    let ticket: String
    let workspaceName: String
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var busy: String?
    @State private var asked: String?
    @State private var failed = false

    var body: some View {
        let group = TeamChatRules.group(in: model.groups.groups, workspace: workspace, ticket: ticket)
        let members = TeamChatRules.members(group, workspace: workspace, workspaceName: workspaceName)
        let waiting = TeamChatRules.pending(model.teamAsked[AppModel.teamKey(workspace, ticket)] ?? [], members: members)
        let candidates = TeamChatRules.candidates(model.workspaces, members: members)
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("Add to this chat").themeFont(20, .semibold)
                    Spacer()
                    ShellCloseButton { dismiss() }
                }
                // One tab today (people come in a later step); kept as a label so the sheet reads like the computer's.
                Text("Workspaces").themeFont(13, .semibold).foregroundStyle(Theme.text)
                    .padding(.horizontal, 12).frame(minHeight: 32)
                    .background(Theme.surface2, in: Capsule())
                    .accessibilityAddTraits(.isHeader).accessibilityIdentifier("team-add-tab-workspaces")
                Text(TeamChatRules.shareNotice + " " + TeamChatRules.removeNotice)
                    .themeFont(13).foregroundStyle(Theme.muted).fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("team-add-notice")
                if let asked {
                    Text("Asked \(workspaceName) to add \(asked). It shows here once it joined.")
                        .themeFont(15).foregroundStyle(Theme.text).accessibilityIdentifier("team-add-asked")
                    Button("Done") { dismiss() }.buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("team-add-done")
                } else if candidates.isEmpty {
                    Text("All your workspaces on this phone are in this chat.")
                        .themeFont(15).foregroundStyle(Theme.muted).accessibilityIdentifier("team-add-empty")
                } else {
                    VStack(spacing: 0) {
                        ForEach(candidates) { ws in row(ws, waiting: waiting.contains(ws.id)) }
                    }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                }
                if failed, let line = model.message {
                    Text(line).themeFont(13).foregroundStyle(Theme.warn).accessibilityIdentifier("team-add-error")
                }
            }.padding(18)
        }
        .background(Theme.bg.ignoresSafeArea())
        .foregroundStyle(Theme.text)
        .accessibilityIdentifier("team-add-sheet")
    }

    private func row(_ ws: Workspace, waiting: Bool) -> some View {
        let name = WorkspaceAlias.name(for: ws)
        return HStack(spacing: 12) {
            WorkspaceBadge(name: name, icon: ws.icon, color: ws.color, size: 34).accessibilityHidden(true)
            Text(name).themeFont(15).lineLimit(1).truncationMode(.tail)
            Spacer(minLength: 8)
            if waiting {
                Text("Adding…").themeFont(13).foregroundStyle(Theme.muted)
            } else {
                Button {
                    busy = ws.id
                    Task {
                        let ok = await model.addToTicketChat(workspace: workspace, ticket: ticket, add: ws)
                        busy = nil
                        if ok { asked = name } else { failed = true }
                    }
                } label: {
                    Text("Add").themeFont(15, .semibold).foregroundStyle(Theme.onBrand)
                        .padding(.horizontal, 16).frame(minHeight: 36)
                        .background(Theme.brand, in: Capsule())
                }.buttonStyle(PressStyle()).frame(minHeight: 44).disabled(busy != nil)
                    .accessibilityLabel("Add \(name)").accessibilityIdentifier("team-add-\(ws.id)")
            }
        }.padding(.horizontal, 14).frame(minHeight: 56)
    }
}

/// Chat info of a ticket chat: who is in it, who added them and when, and which member runs an older orch.
struct TeamChatInfoView: View {
    let workspace: String
    let ticket: String
    let workspaceName: String
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var addShown = false

    var body: some View {
        let group = TeamChatRules.group(in: model.groups.groups, workspace: workspace, ticket: ticket)
        let members = TeamChatRules.members(group, workspace: workspace, workspaceName: workspaceName)
        let waiting = TeamChatRules.pending(model.teamAsked[AppModel.teamKey(workspace, ticket)] ?? [], members: members)
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("Chat info").themeFont(20, .semibold)
                    Spacer()
                    ShellCloseButton { dismiss() }
                }
                Text("In this chat").themeFont(13, .semibold).foregroundStyle(Theme.muted).accessibilityAddTraits(.isHeader)
                VStack(spacing: 0) {
                    ForEach(members, id: \.ws) { m in memberRow(m, members: members) }
                    ForEach(Array(waiting).sorted(), id: \.self) { ws in
                        HStack(spacing: 12) {
                            let name = model.workspace(ws).map(WorkspaceAlias.name(for:)) ?? "Workspace"
                            WorkspaceBadge(name: name, size: 34).opacity(0.6).accessibilityHidden(true)
                            Text(name).themeFont(15).foregroundStyle(Theme.muted)
                            Spacer()
                            Text("Adding…").themeFont(13).foregroundStyle(Theme.muted)
                        }.padding(.horizontal, 14).frame(minHeight: 56).accessibilityIdentifier("team-info-waiting-\(ws)")
                    }
                }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                Text(members.count > 1 ? "A helper answers only when it is named with @. Without @ the helpers stay quiet."
                                       : "Only \(workspaceName)'s helper is in this chat.")
                    .themeFont(13).foregroundStyle(Theme.muted).fixedSize(horizontal: false, vertical: true)
                Button { addShown = true } label: { Label("Add to this chat", systemImage: "plus") }
                    .buttonStyle(SecondaryButtonStyle()).accessibilityIdentifier("team-info-add")
            }.padding(18)
        }
        .background(Theme.bg.ignoresSafeArea())
        .foregroundStyle(Theme.text)
        .accessibilityIdentifier("team-info-sheet")
        .sheet(isPresented: $addShown) {
            AddToChatSheet(workspace: workspace, ticket: ticket, workspaceName: workspaceName).presentationDetents([.medium, .large])
        }
    }

    private func memberRow(_ m: GroupMember, members: [GroupMember]) -> some View {
        let added = TeamChatRules.addedLine(m, host: workspace, hostName: workspaceName)
        let older = TeamChatRules.isOlder(m, members: members, host: workspace)
        return HStack(spacing: 12) {
            WorkspaceBadge(name: m.name, icon: m.look?.icon, color: m.look?.color, size: 34).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(m.name).themeFont(15).lineLimit(1).truncationMode(.tail)
                Text(added).themeFont(12).foregroundStyle(Theme.muted).lineLimit(2)
            }
            Spacer(minLength: 8)
            if older {
                Text(TeamChatRules.olderOrch).themeFont(11, .semibold).foregroundStyle(Theme.warn)
                    .padding(.horizontal, 8).frame(minHeight: 22)
                    .overlay(Capsule().stroke(Theme.warn.opacity(0.6), lineWidth: 1))
                    .accessibilityIdentifier("team-info-older-\(m.ws)")
            }
        }.padding(.horizontal, 14).frame(minHeight: 56)
            .accessibilityElement(children: .combine)
            .accessibilityLabel([m.name, added, older ? TeamChatRules.olderOrch : nil].compactMap { $0 }.joined(separator: ", "))
            .accessibilityIdentifier("team-info-member-\(m.ws)")
    }
}
