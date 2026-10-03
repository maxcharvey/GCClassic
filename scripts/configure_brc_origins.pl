#!/usr/bin/env perl
use strict;
use warnings;
use Getopt::Long qw(GetOptions);
use Time::Local qw(timegm);
my ($run,$hourly,$sourceoff);
GetOptions('run-dir=s'=>\$run,'short-test-hourly'=>\$hourly,'untagged-only'=>\$sourceoff) or die "Invalid options\n";
die "Usage: $0 --run-dir DIR [--short-test-hourly] [--untagged-only]\n" unless defined $run;
my @parents=qw(FSOAP FSOAS BRCSOA NPBRCPOA WTC PBRCPOA DBRCPOA);
my @origins=qw(USA CAN ROW UNT);
my @tags=map {my $p=$_; map {"${p}_$_"} @origins} @parents;
my %text;
for my $file(qw(species_database.yml geoschem_config.yml HEMCO_Config.rc HEMCO_Diagn.rc HISTORY.rc)) {
 open my $fh,'<',"$run/$file" or die "$run/$file: $!";
 local $/; $text{$file}=<$fh>; close $fh;
 die "Already staged origin configuration: $file\n" if $text{$file}=~/BRC_ORIGIN_PROTOTYPE|FSOAP_USA/;
 die "Backup already exists: $file\n" if -e "$run/$file.pre-origins";
}
my ($date,$start_time)=$text{'geoschem_config.yml'}=~/^\s*start_date:\s*\[(\d{8}),\s*(\d{6})\]/m;
my ($end_date,$end_time)=$text{'geoschem_config.yml'}=~/^\s*end_date:\s*\[(\d{8}),\s*(\d{6})\]/m;
die "Missing simulation dates\n" unless defined $date && defined $end_date;
sub epoch {
 my ($d,$t)=@_;my ($year,$month,$day)=$d=~/^(\d{4})(\d{2})(\d{2})$/;
 my ($hour,$minute,$second)=$t=~/^(\d{2})(\d{2})(\d{2})$/;
 return timegm($second,$minute,$hour,$day,$month-1,$year);
}
my $midnight=epoch($date,'000000');
die "Prototype requires a positive period within one native source day\n"
 unless epoch($end_date,$end_time)>epoch($date,$start_time) && epoch($end_date,$end_time)<=$midnight+86400;
my ($year,$month,$day)=$date=~/^(\d{4})(\d{2})(\d{2})$/;
my $source_time=join('/',0+$year,0+$month,0+$day,0);
my $db=$text{'species_database.yml'};
my $extra="\n# BRC_ORIGIN_PROTOTYPE: diagnostic partitions; excluded from physical hygroscopic bins\n";
for my $p(@parents) {
 my ($block)=$db=~/^\Q$p\E:\n(.*?)(?=^[A-Za-z0-9_]+:\s*\n|\z)/msg;
 die "Missing species block $p\n" unless defined $block;
 for my $o(@origins) {
  my $copy=$block;
  $copy=~s/^  FullName:.*$/  FullName: $p diagnostic origin $o/m;
  $copy=~s/^  Is_HygroGrowth:.*$/  Is_HygroGrowth: false/m;
  $copy=~s/^  Background_VV:.*$/  Background_VV: 0.0/m or die "Missing background for $p\n";
  $extra.="${p}_${o}:\n$copy";
 }
}
$text{'species_database.yml'}=$db.$extra;
$text{'geoschem_config.yml'}=~s/(^      - PBRCPOA\s*\n)/$1.join('',map {"      - $_\n"} @tags)/me or die "Cannot append transported origins\n";
my $h=$text{'HEMCO_Config.rc'};
die "FINNv25 GFAS profile backend is not implemented in this v14.8 branch; use validated PBL/pressure injection settings\n"
 if $h=~/^\s*--> FINNV25_GFAS_PROFILE\s*:\s*true\b/m;
die "Requires active harmonized FINNv25 sensitivity\n" unless $h=~/^\s*--> FINNV25_BRC_HARMONIZED_SENSITIVITY\s*:\s*true\b/m;
die "Requires active FINNv25 extension165\n" unless $h=~/^165\s+FINNv25_Inject\s*:\s*on\b/m;
my $enabled=$sourceoff?'false':'true';
$h=~s/(^\s*--> FINNv25_vertical_injection_levels[^\n]*\n)/$1    --> FINNv25_BrC_origin_tags : $enabled # BRC_ORIGIN_PROTOTYPE\n/m or die "Missing FINNv25 options\n";
unless($sourceoff) {
 my %proxy=(FSOAP=>'CO',DBRCPOA=>'BC',NPBRCPOA=>'OC',PBRCPOA=>'OC');
 my %scale=(FSOAP=>'75/286/287',DBRCPOA=>'75/285',NPBRCPOA=>'75/283',PBRCPOA=>'75/284');
 my $fields="# BRC_ORIGIN_PROTOTYPE: partition native inventory BEFORE HEMCO regridding\n";
 for my $p(qw(FSOAP DBRCPOA NPBRCPOA PBRCPOA)) {
  for my $o(qw(USA CAN ROW)) {
   $fields.="165 FINNV25_TAG_${p}_${o} ./ORIGIN_INPUTS/FINN_ORIGINS.$date.nc4 $proxy{$p}_${o} $source_time EF xy molecules/cm^2/s ${p}_${o} $scale{$p} 5 3\n";
  }
 }
 # Do not split any inherited source chain: SOAP inherits the preceding CO
 # record. Append after the final explicit native field and before its close.
 $h=~s/(^165 FINNV25_INJECT_MACR[^\n]*\n)(?=\)\)\)FINNv25_Inject)/$1$fields/m
   or die "Missing safe end of active FINNv25 fields\n";
}
$text{'HEMCO_Config.rc'}=$h;
$text{'HEMCO_Diagn.rc'}.="\n# BRC_ORIGIN_PROTOTYPE\n";
for my $p(qw(FSOAP DBRCPOA NPBRCPOA PBRCPOA)) {
 for my $o(qw(USA CAN ROW)) {
  $text{'HEMCO_Diagn.rc'}.="Emis${p}_${o}_FireColumn ${p}_${o} 165 -1 -1 2 kg/m2/s FINN_origin_flux\n" unless $sourceoff;
 }
}
my @aero=grep {!/^FSOAP_/} @tags;
my %collections=(
 BrCOriginConc=>[map {"SpeciesConcVV_$_"} (@parents,@tags)],
 BrCOriginDryDep=>[map {my $f=$_;map {"${f}_$_"} @aero} qw(DryDep DryDepVel)],
 BrCOriginWetLoss=>[map {my $f=$_;map {"${f}_$_"} @aero} qw(WetLossConv WetLossConvFrac WetLossLS)],
 BrCOriginBudget=>[(map {my $f=$_;map {"${f}_$_"} @tags} qw(BudgetEmisDryDepFull BudgetChemistryFull BudgetTransportFull BudgetMixingFull BudgetConvectionFull)),map {"BudgetWetDepFull_$_"} @aero]);
my @names=qw(BrCOriginConc BrCOriginDryDep BrCOriginWetLoss BrCOriginBudget);
my $hist=$text{'HISTORY.rc'};
$hist=~s/(^COLLECTIONS:[\s\S]*?)(^::)/$1.join('',map {"             '$_',\n"} @names).$2/me or die "Missing HISTORY collections\n";
$hist=~s/\s*\z/\n/;
$hist.="# BRC_ORIGIN_PROTOTYPE: no blank boundary before active appended collections\n";
my $interval=$hourly?'00000000 010000':'00000001 000000';
for my $c(@names) {
 $hist.="  $c.template: '%y4%m2%d2_%h2%n2z.nc4',\n  $c.frequency: $interval\n  $c.duration: $interval\n  $c.mode: 'time-averaged'\n";
 $hist.="  $c.fields: ".join(",\n                    ",map {"'$_'"} @{$collections{$c}}).",\n::\n";
}
$text{'HISTORY.rc'}=$hist;
for my $file(sort keys %text) {
 rename "$run/$file","$run/$file.pre-origins" or die "Backup $file: $!";
 open my $fh,'>',"$run/$file" or die "Write $file: $!";print $fh $text{$file};close $fh or die $!;
 chmod((stat("$run/$file.pre-origins"))[2]&07777,"$run/$file") or die "chmod $file: $!";
}
print "Staged28 diagnostic origins; source partition $enabled; HISTORY interval $interval\n";
