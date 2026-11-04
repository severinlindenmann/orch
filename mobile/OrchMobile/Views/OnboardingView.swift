import SwiftUI
import UIKit

struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @State private var showLink = false
    @State private var showScanner = false
    @State private var link = ""
    @State private var finishing = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Brand().frame(maxWidth: .infinity)
                OrbitMark().frame(width: 72, height: 72).padding(14)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 28))
                    .overlay(RoundedRectangle(cornerRadius: 28).stroke(Theme.border))
                    .frame(maxWidth: .infinity).padding(.top, 28).padding(.bottom, 4)
                Eyebrow(text: "YOUR WORK, WITH YOU", color: Theme.brand)
                ScreenHeading(title: "Let's get connected.", subtitle: "Use the invitation from your relay admin to bring your workspaces along.")
                if model.phase == .notifyStep {
                    notificationStep
                } else {
                    invitationStep
                }
                ModelMessage()
                Text("One connection. Your workspaces.").font(.system(size: 11))
                    .foregroundStyle(Theme.muted).frame(maxWidth: .infinity).padding(.top, 28)
            }.padding(.horizontal, 23).padding(.top, 12).padding(.bottom, 20)
        }
        .sheet(isPresented: $showLink) {
            VStack(alignment: .leading, spacing: 18) {
                Text("Open invitation link").font(.headline)
                TextField("Paste invitation link", text: $link)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .keyboardType(.URL).padding(14).background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
                Button("Open invitation link") {
                    model.openInvite(link); showLink = false
                }.buttonStyle(PrimaryButtonStyle()).disabled(link.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("Close") { showLink = false }.frame(maxWidth: .infinity, minHeight: 44)
            }.padding(23).presentationDetents([.medium]).presentationBackground(Theme.bg)
        }
        .sheet(isPresented: $showScanner) {
            QRScannerView { code in model.openInvite(code); showScanner = false }
        }
    }

    @ViewBuilder private var invitationStep: some View {
        switch model.inviteState {
        case .none:
            VStack(spacing: 10) {
                Button {
                    if let value = UIPasteboard.general.string, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        model.openInvite(value)
                    } else { showLink = true }
                } label: { Text("Open invitation link  ↗") }.buttonStyle(PrimaryButtonStyle())
                Button { showScanner = true } label: { Label("Scan QR code", systemImage: "qrcode.viewfinder") }
                    .buttonStyle(SecondaryButtonStyle())
                Button("Use the sample invitation") { model.openSampleInvite() }
                    .font(.system(size: 11)).foregroundStyle(Theme.muted)
                    .frame(maxWidth: .infinity, minHeight: 44).accessibilityIdentifier("sample-invite")
            }
        case .found(let host):
            VStack(alignment: .leading, spacing: 12) {
                Text("●  \(host)").font(.system(size: 11)).foregroundStyle(Theme.brand)
                Text("Your relay admin invited this phone.").font(.system(size: 13))
            }.orchCard()
            Button("Connect this phone") {
                Task { await model.connect(phoneName: UIDevice.current.name) }
            }.buttonStyle(PrimaryButtonStyle())
        case .connecting:
            ProgressView("Connecting this phone…").frame(maxWidth: .infinity, minHeight: 80)
        }
    }

    private var notificationStep: some View {
        VStack(spacing: 18) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Know when you're needed.").font(.system(size: 17, weight: .semibold))
                Text("Get a notification when a workspace has a question for you.")
                    .font(.system(size: 13)).foregroundStyle(Theme.muted)
                ForEach(model.pairedWorkspaces) { workspace in
                    HStack { Text(workspace.name); Spacer(); Image(systemName: "checkmark").foregroundStyle(Theme.brand) }
                        .font(.system(size: 13)).padding(.vertical, 6)
                }
            }.orchCard()
            Button("Allow notifications") { finish(true) }.buttonStyle(PrimaryButtonStyle())
            Button("Not now") { finish(false) }.foregroundStyle(Theme.muted).frame(maxWidth: .infinity, minHeight: 44)
            if finishing { ProgressView() }
        }.disabled(finishing)
    }

    private func finish(_ allowed: Bool) {
        finishing = true
        Task { await model.finishSetup(allowNotifications: allowed); finishing = false }
    }
}
